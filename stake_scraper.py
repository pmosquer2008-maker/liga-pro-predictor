"""
stake_scraper.py — Extractor de cuotas Pre-Match para Stake Colombia
Diseñado para evadir bloqueos: Entra, extrae las cuotas futuras, guarda y sale.
"""

import asyncio
import time
import random
import logging
from playwright.async_api import async_playwright
import db_manager
from unidecode import unidecode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [STAKE_SCRAPER] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger()

# URL general de Tenis de Mesa (Incluye próximos partidos)
STAKE_TT_URL = "https://stake.com.co/sports/table-tennis"

def normalize_name(name: str) -> str:
    """Normaliza nombres para que coincidan con los de Sofascore (Ej: 'Jiri Pleskot' -> 'Pleskot J.')"""
    name = unidecode(name).strip()
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[-1]} {parts[0][0]}."
    return name

async def random_delay(min_sec=1.5, max_sec=3.5):
    """Simula comportamiento humano para no activar las alarmas de Cloudflare"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))

async def extract_odds():
    log.info("Iniciando modo sigilo: Conectando con Stake...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, # Si Stake te pide Captcha, ponlo en False una vez, resuélvelo y vuelve a True.
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1920,1080"
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-CO",
            timezone_id="America/Bogota"
        )
        
        page = await context.new_page()
        
        try:
            await page.goto(STAKE_TT_URL, wait_until="domcontentloaded", timeout=60000)
            log.info("✅ Página cargada. Esperando renderizado de cuotas...")
            await random_delay(4.0, 6.0) # Espera a que los WebSockets de Stake inyecten los números
            
            # Buscamos contenedores de partidos (Stake usa clases dinámicas, buscaremos botones de cuotas)
            # El selector busca contenedores genéricos que agrupan a los equipos
            matches = await page.query_selector_all('div[data-test="fixture"], div.fixture-preview, div[class*="sports-fixture"]')
            
            if not matches:
                # Fallback: a veces Stake envuelve todo en enlaces a los partidos
                matches = await page.query_selector_all('a[href*="/sports/table-tennis/matches/"]')

            log.info(f"Se encontraron {len(matches)} posibles partidos programados.")
            
            partidos_guardados = 0
            
            for match in matches:
                try:
                    text_content = await match.inner_text()
                    lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                    
                    if len(lines) >= 4:
                        # Extraemos nombres (sulen estar en las primeras líneas tras limpiar horas)
                        # Ignoramos líneas de tiempo como "Hoy 15:00" o "Live"
                        clean_lines = [l for l in lines if not l.replace(':','').isdigit() and l.lower() != "live"]
                        
                        if len(clean_lines) >= 4:
                            player_1 = normalize_name(clean_lines[0])
                            player_2 = normalize_name(clean_lines[1])
                            
                            # Filtramos los decimales (cuotas)
                            odds = [float(l) for l in clean_lines if l.replace('.','',1).isdigit()]
                            
                            if len(odds) >= 2:
                                odd_1, odd_2 = odds[0], odds[1]
                                match_id = f"{player_1}_{player_2}".replace(" ", "_")
                                
                                # Guardado atómico en base de datos
                                db_manager.save_odds(match_id, odd_1, odd_2)
                                partidos_guardados += 1
                                log.info(f"Cuotas Pre-Match: {player_1} [{odd_1}] vs {player_2} [{odd_2}]")
                except Exception as e:
                    continue # Ignorar si un bloque no tiene el formato correcto
                    
            log.info(f"Misión cumplida. {partidos_guardados} líneas de cuotas actualizadas en SQLite.")
                
        except Exception as e:
            log.error(f"Error durante la extracción: {e}")
        finally:
            log.info("Cerrando navegador para evitar detección...")
            await browser.close()

if __name__ == "__main__":
    asyncio.run(extract_odds())