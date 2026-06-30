"""
run.py — Orquestador Pre-Match (Batch Processing)
Ejecuta descargas profundas cada 3 horas para no saturar la PC.
"""

import subprocess
import sys
import time
import threading
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SYSTEM] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger()
PYTHON = sys.executable

# Control de procesos
active_processes = []
is_running = True

def run_periodic_task(name, script_name, interval_seconds):
    """Ejecuta un scraper, espera los minutos indicados, y repite sin hacer spam."""
    while is_running:
        log.info(f"▶ Iniciando {name}...")
        try:
            p = subprocess.Popen([PYTHON, script_name])
            active_processes.append(p)
            p.wait()  # Espera a que termine su trabajo
            if p in active_processes:
                active_processes.remove(p)
        except Exception as e:
            log.error(f"Error en {name}: {e}")
        
        # Espera silenciosa e interrumpible
        for _ in range(interval_seconds):
            if not is_running:
                break
            time.sleep(1)

def run_continuous_task(name, script_name, is_streamlit=False):
    """Mantiene vivos los procesos continuos como el Dashboard."""
    while is_running:
        log.info(f"▶ Iniciando {name}...")
        try:
            if is_streamlit:
                cmd = [PYTHON, "-m", "streamlit", "run", script_name, "--server.port", "8501", "--server.headless", "true"]
            else:
                cmd = [PYTHON, script_name]
                
            p = subprocess.Popen(cmd)
            active_processes.append(p)
            p.wait()  
            
            if p in active_processes:
                active_processes.remove(p)
                
            if is_running:
                log.warning(f"⚠️ {name} se cerró. Reiniciando en 5s...")
                time.sleep(5)
        except Exception as e:
            log.error(f"Error crítico en {name}: {e}")
            time.sleep(5)

def main():
    global is_running
    log.info("🚀 Iniciando Czech Liga Pro Income Engine (Modo Pre-Match)...")
    print("\n" + "="*60)
    print("🤖 SISTEMA EN LÍNEA. Presiona [Ctrl + C] para detener todo.")
    print("="*60 + "\n")

    # 1. Tareas Periódicas (Scrapers cada 3 horas = 10800 segundos)
    threading.Thread(target=run_periodic_task, args=("Scraper Historial (Sofascore)", "tournament_scraper.py", 10800), daemon=True).start()
    
    time.sleep(10) # Dale tiempo a Sofascore de crear/actualizar la base de datos
    
    threading.Thread(target=run_periodic_task, args=("Scraper Cuotas (Stake)", "stake_scraper.py", 10800), daemon=True).start()

    # 2. Tareas Continuas (Desactivamos Live Scraper y Predictor temporalmente para ahorrar CPU)
    # threading.Thread(target=run_continuous_task, args=("Predictor Matemático", "Predictor.py"), daemon=True).start()
    # threading.Thread(target=run_continuous_task, args=("Live Scraper", "live_scraper.py"), daemon=True).start()
    
    # 3. Encender Dashboard Visual
    threading.Thread(target=run_continuous_task, args=("Dashboard Visual", "dashboard.py", True), daemon=True).start()

    # Bucle principal esperando la orden de apagado manual
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("\n🛑 [Ctrl + C] detectado. Apagando todos los motores suavemente...")
        is_running = False
        for p in active_processes:
            try:
                p.terminate()
            except:
                pass
        log.info("🔌 Sistema completamente apagado. ¡Buen trading!")
        sys.exit(0)

if __name__ == "__main__":
    main()