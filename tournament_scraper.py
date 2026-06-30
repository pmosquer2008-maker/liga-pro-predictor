"""
tournament_scraper.py — Czech Liga Pro | Lectura Profunda (Deep Scan)
Garantiza leer 300 partidos pasados y todos los futuros por si la PC estuvo apagada 24h+.
"""

import asyncio
import json
import re
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from playwright.async_api import async_playwright
import db_manager

TOURNAMENT_URL = "https://www.sofascore.com/es/table-tennis/tournament/czech-republic/czech-liga-pro/19039"
OUTPUT_FILE = Path("tournament_data.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SCRAPER] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger()

def compute_elo_and_stats(matches, k=32, base=1500):
    """Calcula el ELO y estadísticas procesando el historial desde el más antiguo al más reciente."""
    ratings = defaultdict(lambda: base)
    stats = defaultdict(lambda: {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0, "matches": 0})
    last_played = {} 
    
    for m in reversed(matches):
        if m["status"] != "finalizado" or m["sets"]["home"] == m["sets"]["away"]:
            continue
            
        home, away = m["home"], m["away"]
        sh, sa = m["sets"]["home"], m["sets"]["away"]
        
        if m.get("start_time"):
            last_played[home] = m["start_time"]
            last_played[away] = m["start_time"]
            
        home_won = sh > sa
        stats[home]["matches"] += 1
        stats[away]["matches"] += 1
        stats[home]["sets_won"] += sh
        stats[home]["sets_lost"] += sa
        stats[away]["sets_won"] += sa
        stats[away]["sets_lost"] += sh
        
        if home_won:
            stats[home]["wins"] += 1
            stats[away]["losses"] += 1
        else:
            stats[away]["wins"] += 1
            stats[home]["losses"] += 1

        r_h, r_a = ratings[home], ratings[away]
        exp_h = 1 / (1 + 10 ** ((r_a - r_h) / 400))
        score_h = 1.0 if home_won else 0.0
        total_sets = sh + sa
        
        bonus = 1.2 if total_sets == 3 else (1.0 if total_sets == 4 else 0.85)
        
        ratings[home] = r_h + k * bonus * (score_h - exp_h)
        ratings[away] = r_a + k * bonus * ((1 - score_h) - (1 - exp_h))
        
    return dict(ratings), dict(stats), last_played

def parse_events(payload: dict) -> list[dict]:
    events_raw = payload.get("events") or payload.get("tournamentTeamEvents") or []
    results = []
    for e in events_raw:
        home = (e.get("homeTeam") or e.get("homePlayer") or {}).get("name", "?")
        away = (e.get("awayTeam") or e.get("awayPlayer") or {}).get("name", "?")
        hs = e.get("homeScore", {})
        as_ = e.get("awayScore", {})

        sets_detail = []
        for i in range(1, 8):
            k = f"period{i}"
            h, a = hs.get(k), as_.get(k)
            if h is not None and a is not None:
                sets_detail.append({"set": i, "home": h, "away": a})

        status_map = {"inprogress": "en_curso", "finished": "finalizado", "notstarted": "programado"}
        raw_status = e.get("status", {}).get("type", "unknown")
        status = status_map.get(raw_status, raw_status)

        start_ts = e.get("startTimestamp")
        start_iso = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat() if start_ts else None

        sh, sa = hs.get("current", 0), as_.get("current", 0)
        results.append({
            "id": e.get("id"),
            "status": status,
            "start_time": start_iso,
            "home": home,
            "away": away,
            "sets": {"home": sh, "away": sa},
            "sets_detail": sets_detail,
            "winner": (home if sh > sa else away if sa > sh else None) if status == "finalizado" else None,
            "slug": e.get("slug", ""),
        })
    return results

async def fetch_json(page, path: str) -> dict | None:
    js = f"""
    async () => {{
        try {{
            const r = await fetch('{path}', {{
                credentials: 'include',
                headers: {{'Accept': 'application/json'}}
            }});
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

async def scrape():
    db_manager.init_db()
    
    all_finished = []
    seen_ids = set()
    
    try:
        with db_manager.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM matches")
            seen_ids = {row[0] for row in c.fetchall()}
            log.info(f"DB Local: Encontrados {len(seen_ids)} partidos previos.")
    except Exception as e:
        pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        ids = {"tournament": "19039", "season": None}

        async def sniff(response):
            if "/unique-tournament/19039" in response.url:
                m_s = re.search(r"/season/(\d+)", response.url)
                if m_s: ids["season"] = m_s.group(1)

        page.on("response", sniff)

        log.info("Adquiriendo tokens del torneo...")
        await page.goto(TOURNAMENT_URL, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)

        tid = ids["tournament"]
        sid = ids["season"]

        if not sid:
            seasons_payload = await fetch_json(page, f"/api/v1/unique-tournament/{tid}/seasons")
            if seasons_payload and "seasons" in seasons_payload and len(seasons_payload["seasons"]) > 0:
                sid = str(seasons_payload["seasons"][0]["id"])

        if not tid or not sid:
            log.error("No se encontraron IDs. Cerrando...")
            await browser.close()
            return

        all_upcoming = []
        new_matches_added = 0

        # ── LECTURA PROFUNDA EXTREMA (20 páginas = ~300 partidos para recuperar apagones largos) ──
        log.info("Modo Deep Scan Activado: Leyendo hasta 20 páginas hacia atrás...")
        page_num = 0
        consecutive_empty = 0

        # Aumentamos a 20 páginas para garantizar que un apagón de 24h no deje huecos
        while consecutive_empty < 2 and page_num < 20:
            path = f"/api/v1/unique-tournament/{tid}/season/{sid}/events/last/{page_num}"
            payload = await fetch_json(page, path)

            if not payload:
                consecutive_empty += 1
                page_num += 1
                continue

            events = parse_events(payload)
            finished_in_page = [e for e in events if e["status"] == "finalizado"]

            if not finished_in_page:
                consecutive_empty += 1
            else:
                consecutive_empty = 0
                for e in finished_in_page:
                    if e["id"] not in seen_ids:
                        seen_ids.add(e["id"])
                        all_finished.append(e)
                        new_matches_added += 1
                log.info(f"Página de historial {page_num} procesada.")
            
            page_num += 1
            await asyncio.sleep(0.5)

        log.info(f"[{new_matches_added}] partidos NUEVOS recuperados y añadidos a la BD local.")

        # ── Próximos partidos: 4 pagines (aprox 60 partits) ──
        log.info("Leyendo próximos partidos (Cartelera)...")
        for np in range(4):
            path = f"/api/v1/unique-tournament/{tid}/season/{sid}/events/next/{np}"
            payload = await fetch_json(page, path)
            if payload:
                events = parse_events(payload)
                upcoming = [e for e in events if e["status"] == "programado"]
                if not upcoming: break
                for e in upcoming:
                    all_upcoming.append(e)
            await asyncio.sleep(0.5)
        log.info(f"Encontrados {len(all_upcoming)} partidos programados.")

        await browser.close()

        all_finished.sort(key=lambda x: x.get("start_time") or "", reverse=True)
        all_upcoming.sort(key=lambda x: x.get("start_time") or "")

        # Recalcular ELO
        elo_ratings, player_stats, last_played_dict = compute_elo_and_stats(all_finished)

        log.info("Actualizando base de datos SQLite...")
        db_manager.save_matches(all_finished)
        db_manager.save_players(elo_ratings, player_stats, last_played_dict)
        db_manager.save_upcoming(all_upcoming)

        # JSON backup
        output = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "tournament_id": tid, "season_id": sid,
            "total_finished": len(all_finished),
            "total_upcoming": len(all_upcoming),
            "elo_ratings": elo_ratings, "player_stats": player_stats,
            "finished": all_finished, "upcoming": all_upcoming,
        }
        tmp_file = OUTPUT_FILE.with_suffix('.tmp')
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, OUTPUT_FILE)
        log.info("Scraping Finalizado Exitosamente.")

if __name__ == "__main__":
    asyncio.run(scrape())