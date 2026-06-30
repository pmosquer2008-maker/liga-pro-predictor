"""
live_scraper.py — Monitoreo en vivo punto a punto (Czech Liga Pro)
Busca el partido en curso y actualiza data.json de forma atómica.
"""

import asyncio
import json
import os
import logging
import time
from pathlib import Path
from playwright.async_api import async_playwright

TOURNAMENT_FILE = Path("tournament_data.json")
LIVE_DATA_FILE = Path("data.json")
TMP_DATA_FILE = Path("data.json.tmp")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [LIVE_SCRAPER] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger()

async def fetch_api(page, path: str) -> dict | None:
    """Ejecuta un fetch interno en el contexto del navegador para eludir Cloudflare."""
    js = f"""
    async () => {{
        try {{
            const r = await fetch('{path}', {{ headers: {{'Accept': 'application/json'}} }});
            return {{status: r.status, body: await r.text()}};
        }} catch(e) {{ return {{status: 0, body: e.message}}; }}
    }}
    """
    result = await page.evaluate(js)
    if result["status"] == 200:
        try:
            return json.loads(result["body"])
        except Exception:
            return None
    return None

def write_atomic_json(data: dict, target_file: Path, tmp_file: Path):
    """Escritura atómica para que Predictor.py nunca lea un archivo corrupto."""
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, target_file)

async def monitor_live_match():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()
        
        # Cargar la página base para obtener las cookies y el contexto
        await page.goto("https://www.sofascore.com/es/table-tennis", wait_until="domcontentloaded")
        
        current_match_id = None
        
        while True:
            # 1. Buscar cuál es el partido activo usando los datos del tournament_scraper
            if not current_match_id:
                if TOURNAMENT_FILE.exists():
                    try:
                        t_data = json.loads(TOURNAMENT_FILE.read_text(encoding="utf-8"))
                        # Asumimos que el primer 'upcoming' podría haber empezado
                        if t_data.get("upcoming"):
                            first_upcoming = t_data["upcoming"][0]
                            # Consultar el estado real de este partido
                            event_data = await fetch_api(page, f"/api/v1/event/{first_upcoming['id']}")
                            if event_data and event_data.get("event", {}).get("status", {}).get("type") == "inprogress":
                                current_match_id = first_upcoming['id']
                                log.info(f"🎾 Partido en curso detectado: {first_upcoming['home']} vs {first_upcoming['away']} (ID: {current_match_id})")
                    except Exception as e:
                        log.error(f"Error leyendo torneo: {e}")
            
            # 2. Scrapear punto a punto el partido activo
            if current_match_id:
                event_payload = await fetch_api(page, f"/api/v1/event/{current_match_id}")
                if event_payload and "event" in event_payload:
                    ev = event_payload["event"]
                    status = ev.get("status", {}).get("type")
                    
                    if status == "finished":
                        log.info("Partido finalizado. Buscando el siguiente...")
                        current_match_id = None
                        await asyncio.sleep(10)
                        continue

                    # Extraer estructura de puntos
                    home_name = ev.get("homeTeam", {}).get("name", "Home")
                    away_name = ev.get("awayTeam", {}).get("name", "Away")
                    hs = ev.get("homeScore", {})
                    as_ = ev.get("awayScore", {})
                    
                    sets_detail = []
                    for i in range(1, 8):
                        k = f"period{i}"
                        if k in hs and k in as_:
                            sets_detail.append({"set": i, "home": hs[k], "away": as_[k]})
                    
                    # Estructura requerida por Predictor.py
                    live_data = {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                        "status": "en_curso",
                        "home": home_name,
                        "away": away_name,
                        "sets": {"home": hs.get("display", 0), "away": as_.get("display", 0)},
                        "sets_detail": sets_detail,
                        "current_set": len(sets_detail) + 1 if ev.get("status", {}).get("code") != 100 else len(sets_detail),
                        "current_points": {"home": hs.get("current", 0), "away": as_.get("current", 0)},
                        "raw_event_id": str(current_match_id)
                    }
                    
                    write_atomic_json(live_data, LIVE_DATA_FILE, TMP_DATA_FILE)
                    log.info(f"Punto actualizado -> {home_name} {live_data['current_points']['home']} - {live_data['current_points']['away']} {away_name}")
            
            await asyncio.sleep(2.5) # Polling agresivo pero seguro (2.5 seg)

if __name__ == "__main__":
    try:
        asyncio.run(monitor_live_match())
    except KeyboardInterrupt:
        log.info("Scraper en vivo detenido.")