"""
tournament_scraper.py — Czech Liga Pro | Lectura Profunda (Deep Scan)
Garantiza leer 300 partidos pasados y todos los futuros por si la PC estuvo apagada 24h+.
Optimizada 100% para SQLite (Sin JSON residuales) + Escudo Anti-Borrado.
"""

import asyncio
import json
import re
import logging
from datetime import datetime, timezone
from collections import defaultdict
from playwright.async_api import async_playwright
import db_manager

TOURNAMENT_URL = "https://www.sofascore.com/es/table-tennis/tournament/czech-republic/czech-liga-pro/19039"

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
    # 🟢 ANTÍDOTO ANTI-CACHÉ CORREGIDO: Evitamos alterar la URL (Sofascore lo rechaza).
    # Usamos directivas estrictas de 'no-store' en la configuración de la cabecera.
    js = f"""
    async () => {{
        try {{
            const r = await fetch('{path}', {{
                credentials: 'include',
                cache: 'no-store',
                headers: {{
                    'Accept': 'application/json',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache'
                }}
            }});
            if (r.status === 200) {{
                return {{status: r.status, body: await r.text()}};
            }} else {{
                return {{status: r.status, body: ""}};
            }}
        }} catch(e) {{ return {{status: 0, body: e.message}}; }}
    }}
    """
    result = await page.evaluate(js)
    if result["status"] == 200:
        try:
            return json.loads(result["body"])
        except Exception:
            return None
    else:
        log.warning(f"⚠️ [API ERROR] Fallo al leer {path} - Código HTTP: {result['status']}")
        return None

async def scrape():
    db_manager.init_db()
    log.info(f"Iniciando ciclo de Scraping - Hora del servidor: {datetime.now(timezone.utc).isoformat()}")
    
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

    ids = {"season": None}
    tid = "19039"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security"
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
            timezone_id="America/Bogota"
        )
        
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = await context.new_page()
        
        log.info("Entrando a la página (Modo Stealth Asíncrono Anti-Caché)...")
        await page.goto(TOURNAMENT_URL)
        
        await page.wait_for_timeout(8000) 

        async def sniff(response):
            if "/unique-tournament/19039" in response.url:
                m_s = re.search(r"/season/(\d+)", response.url)
                if m_s: ids["season"] = m_s.group(1)

        page.on("response", sniff)

        log.info("Adquiriendo tokens del torneo...")
        await page.goto(TOURNAMENT_URL, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)

        sid = ids["season"]

        if not sid:
            seasons_payload = await fetch_json(page, f"/api/v1/unique-tournament/{tid}/seasons")
            if seasons_payload and "seasons" in seasons_payload and len(seasons_payload["seasons"]) > 0:
                sid = str(seasons_payload["seasons"][0]["id"])

        if not tid or not sid:
            log.error("No se encontraron IDs (Posible Bloqueo). Cerrando sin actualizar BD...")
            await browser.close()
            return

        all_upcoming = []
        new_matches_added = 0
        
        # 🛡️ ESCUDO ANTI-BORRADO: Esta variable vigila que la API realmente responda
        api_working = False 

        log.info("Modo Deep Scan Activado: Leyendo hasta 20 páginas hacia atrás...")
        page_num = 0
        consecutive_empty = 0

        while consecutive_empty < 2 and page_num < 20:
            path = f"/api/v1/unique-tournament/{tid}/season/{sid}/events/last/{page_num}"
            payload = await fetch_json(page, path)

            if payload is None:
                consecutive_empty += 1
                page_num += 1
                continue
                
            api_working = True # ¡Confirmamos que la API no nos está bloqueando!

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
            
        # Si api_working es False, significa que la API rechazó todo. Abortamos para no borrar la DB.
        if not api_working:
            log.error("❌ FALLO MASIVO DE API (Bloqueo de Sofascore). Abortando para PROTEGER los datos actuales de tu BD...")
            await browser.close()
            return

        log.info(f"[{new_matches_added}] partidos NUEVOS recuperados.")

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
        log.info(f"Encontrados {len(all_upcoming)} partidos programados fresquitos.")

        await browser.close()

    # Ordenar los nuevos encontrados
    all_finished.sort(key=lambda x: x.get("start_time") or "", reverse=True)
    all_upcoming.sort(key=lambda x: x.get("start_time") or "")

    # ── RECONSTRUCCIÓN DEL HISTORIAL PARA ELO MATEMÁTICAMENTE CORRECTO ──
    log.info("Integrando historial completo de la BD para calcular ELO exacto...")
    all_historical = []
    try:
        with db_manager.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id, start_time, home, away, home_sets, away_sets, status FROM matches WHERE status='finalizado'")
            for row in c.fetchall():
                all_historical.append({
                    "id": row[0],
                    "start_time": row[1],
                    "home": row[2],
                    "away": row[3],
                    "sets": {"home": row[4], "away": row[5]},
                    "status": row[6]
                })
    except Exception as e:
        log.error(f"Error extrayendo DB local: {e}")

    # Fusionar los partidos viejos con los recién descargados (evitando duplicados)
    for new_m in all_finished:
        if not any(m["id"] == new_m["id"] for m in all_historical):
            all_historical.append(new_m)

    # Ordenar cronológicamente (más recientes primero, la función compute_elo lo reversa internamente)
    all_historical.sort(key=lambda x: x.get("start_time") or "", reverse=True)

    # Calcular ELO y Estadísticas con el 100% de los datos
    elo_ratings, player_stats, last_played_dict = compute_elo_and_stats(all_historical)

    # 🔴 GUARDADO DIRECTO A LA BASE DE DATOS (.db)
    log.info("Actualizando base de datos SQLite...")
    db_manager.save_matches(all_finished) # Solo añadimos a la DB los nuevos que faltaban
    db_manager.save_players(elo_ratings, player_stats, last_played_dict) # Sobreescribimos stats correctos
    db_manager.save_upcoming(all_upcoming) # Reemplazamos la cartelera con la de hoy

    log.info("Scraping Finalizado Exitosamente (Modo DB-Only + Anti-Wipe).")

if __name__ == "__main__":
    asyncio.run(scrape())
