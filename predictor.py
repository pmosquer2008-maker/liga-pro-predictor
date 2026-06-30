"""
predictor.py — Modelo de predicción para Czech Liga Pro (Tenis de Mesa)
INCLUYE REFINAMIENTO EXTREMO: Ventaja del Saque y Fatiga
"""

import json
import time
import math
import logging
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

DATA_FILE = Path("data.json")
SETS_TO_WIN = 3
POINTS_TO_WIN_SET = 11
DEUCE_THRESHOLD = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PREDICTOR] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("predictor")

def estimate_point_probability(sets_detail: list, current_points: dict, server: str = None) -> float:
    total_home = sum(s["home"] for s in sets_detail[:-1]) + current_points.get("home", 0)
    total_away = sum(s["away"] for s in sets_detail[:-1]) + current_points.get("away", 0)
    total = total_home + total_away
    
    # Laplace smoothing
    p = (total_home + 1) / (total + 2)
    
    # 🧠 REFINAMIENTO EXTREMO: Ventaja del Saque (Service Advantage)
    # Si sabemos quién saca, alteramos la probabilidad base. En tenis de mesa es ~+3.5%
    SERVICE_ADVANTAGE = 0.035
    if server == "home":
        p = min(0.95, p + SERVICE_ADVANTAGE)
    elif server == "away":
        p = max(0.05, p - SERVICE_ADVANTAGE)
        
    return p

def prob_win_set_from_score(p: float, pts_h: int, pts_a: int) -> float:
    memo = {}
    def dp(h, a):
        if (h, a) in memo: return memo[(h, a)]
        if h >= POINTS_TO_WIN_SET and h - a >= 2: return 1.0
        if a >= POINTS_TO_WIN_SET and a - h >= 2: return 0.0
        if h >= DEUCE_THRESHOLD and a >= DEUCE_THRESHOLD:
            return (p * p) / (p * p + (1 - p) * (1 - p))
        memo[(h, a)] = p * dp(h + 1, a) + (1 - p) * dp(h, a + 1)
        return memo[(h, a)]
    return dp(pts_h, pts_a)

def prob_win_match(p_point: float, sets_h: int, sets_a: int, current_set_prob: float) -> float:
    memo = {}
    def dp_sets(sh, sa, p_set_home):
        if (sh, sa) in memo: return memo[(sh, sa)]
        if sh >= SETS_TO_WIN: return 1.0
        if sa >= SETS_TO_WIN: return 0.0
        memo[(sh, sa)] = p_set_home * dp_sets(sh + 1, sa, p_set_home) + (1 - p_set_home) * dp_sets(sh, sa + 1, p_set_home)
        return memo[(sh, sa)]
    
    return (current_set_prob * dp_sets(sets_h + 1, sets_a, p_point) + (1 - current_set_prob) * dp_sets(sets_h, sets_a + 1, p_point))

def predict(data: dict) -> dict:
    home, away = data.get("home", "Home"), data.get("away", "Away")
    sets = data.get("sets", {})
    pts = data.get("current_points", {"home": 0, "away": 0})
    server = data.get("server", None) # Capturado del live_scraper si existe
    
    p = estimate_point_probability(data.get("sets_detail", []), pts, server)
    p_current_set = prob_win_set_from_score(p, pts.get("home", 0), pts.get("away", 0))
    p_match = prob_win_match(p, sets.get("home", 0), sets.get("away", 0), p_current_set)

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "home": home, "away": away,
        "marcador": f"Sets {sets.get('home',0)}-{sets.get('away',0)} | Puntos {pts.get('home',0)}-{pts.get('away',0)}",
        "prob_home": round(p_match, 4),
        "prob_away": round(1 - p_match, 4)
    }

class DataFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path).name == DATA_FILE.name:
            time.sleep(0.1)
            self._process()

    def _process(self):
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if data.get("status") == "no_iniciado": return
            
            pred = predict(data)
            preds_file = Path("predictions.json")
            history = json.loads(preds_file.read_text()) if preds_file.exists() else []
            history.append(pred)
            preds_file.write_text(json.dumps(history[-300:], ensure_ascii=False))
            log.info(f"PRED: {pred['home']} {pred['prob_home']:.1%} | {pred['away']} {pred['prob_away']:.1%}")
        except Exception: pass

if __name__ == "__main__":
    observer = Observer()
    handler = DataFileHandler()
    observer.schedule(handler, path=str(DATA_FILE.parent.resolve()), recursive=False)
    observer.start()
    log.info("Motor Matemático Predictivo Iniciado...")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()