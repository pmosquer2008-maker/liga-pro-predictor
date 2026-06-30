"""
backtesting.py — Motor de Simulación Histórica (Time Machine)
Evalúa cómo le habría ido al modelo si hubieras apostado en el pasado.
"""

import sqlite3
import pandas as pd
from pathlib import Path
import db_manager

# Configuración de simulación
BANKROLL_INICIAL = 1000.0
UMBRAL_PROBABILIDAD = 0.65 # Apostamos solo si el modelo le da > 65% de victoria al jugador
CUOTA_PROMEDIO = 1.85 # Al no tener las cuotas reales pasadas, usamos una cuota conservadora estándar

def run_backtest():
    print("="*60)
    print("🚀 INICIANDO BACKTESTING ENGINE (CZECH LIGA PRO)")
    print("="*60)
    
    try:
        conn = db_manager.get_connection()
        # Traer todos los partidos finalizados
        df_matches = pd.read_sql("SELECT * FROM matches WHERE status='finalizado' ORDER BY start_time ASC", conn)
        df_players = pd.read_sql("SELECT name, elo FROM players", conn)
        elo_dict = dict(zip(df_players.name, df_players.elo))
    except Exception as e:
        print(f"Error leyendo base de datos: {e}")
        return

    if df_matches.empty:
        print("No hay suficientes partidos en la base de datos para simular.")
        return

    bankroll = BANKROLL_INICIAL
    apuestas_ganadas = 0
    apuestas_perdidas = 0
    apuestas_totales = 0
    
    print(f"Analizando {len(df_matches)} partidos históricos...\n")

    for _, match in df_matches.iterrows():
        home, away = match['home'], match['away']
        elo_h = elo_dict.get(home, 1500)
        elo_a = elo_dict.get(away, 1500)
        
        # Probabilidad pre-match usando el ELO capturado
        prob_h = 1 / (1 + 10 ** ((elo_a - elo_h) / 400))
        prob_a = 1 - prob_h
        
        apuesta_a = None
        
        # Estrategia de Value Betting (Solo apostamos si hay confianza alta)
        if prob_h >= UMBRAL_PROBABILIDAD:
            apuesta_a = "home"
        elif prob_a >= UMBRAL_PROBABILIDAD:
            apuesta_a = "away"
            
        # Si el modelo decidió apostar, verificamos el resultado real
        if apuesta_a:
            apuestas_totales += 1
            home_won = match['home_sets'] > match['away_sets']
            
            # Criterio de Stake Fijo (Unidad) para backtesting: 2% de la banca
            stake = bankroll * 0.02 
            
            if (apuesta_a == "home" and home_won) or (apuesta_a == "away" and not home_won):
                apuestas_ganadas += 1
                ganancia = stake * (CUOTA_PROMEDIO - 1)
                bankroll += ganancia
            else:
                apuestas_perdidas += 1
                bankroll -= stake

    # ── Resultados del Backtest ──
    win_rate = (apuestas_ganadas / apuestas_totales) * 100 if apuestas_totales > 0 else 0
    roi = ((bankroll - BANKROLL_INICIAL) / BANKROLL_INICIAL) * 100
    
    print("📊 RESULTADOS DEL BACKTEST:")
    print("-" * 30)
    print(f"Partidos Simulados:    {apuestas_totales}")
    print(f"Apuestas Ganadas:      {apuestas_ganadas}")
    print(f"Apuestas Perdidas:     {apuestas_perdidas}")
    print(f"Efectividad (Win Rate): {win_rate:.1f}%")
    print("-" * 30)
    print(f"Bankroll Inicial:      ${BANKROLL_INICIAL:.2f}")
    print(f"Bankroll Final:        ${bankroll:.2f}")
    
    if bankroll > BANKROLL_INICIAL:
        print(f"Beneficio Neto:        +${(bankroll - BANKROLL_INICIAL):.2f} 🟢")
        print(f"ROI Total:             +{roi:.2f}% 📈")
    else:
        print(f"Pérdida Neta:          -${(BANKROLL_INICIAL - bankroll):.2f} 🔴")
        print(f"ROI Total:             {roi:.2f}% 📉")
        
    print("="*60)
    print("TIP: Ajusta las variables UMBRAL_PROBABILIDAD y CUOTA_PROMEDIO en el script")
    print("para descubrir cuál es la estrategia matemática más rentable.")

if __name__ == "__main__":
    run_backtest()