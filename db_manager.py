import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = "database.db"

def get_connection():
    """Establece la conexión a la base de datos SQLite."""
    return sqlite3.connect(DB_PATH)

def init_db():
    """Inicializa las tablas si no existen."""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            start_time TEXT,
            home TEXT,
            away TEXT,
            home_sets INTEGER,
            away_sets INTEGER,
            status TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY,
            elo INTEGER,
            wins INTEGER,
            losses INTEGER,
            matches INTEGER,
            sets_won INTEGER,
            sets_lost INTEGER,
            last_played TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS upcoming (
            id TEXT PRIMARY KEY,
            start_time TEXT,
            home TEXT,
            away TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS live_odds (
            match_id TEXT PRIMARY KEY,
            home_odd REAL,
            away_odd REAL,
            last_update TEXT
        )
        """)
        conn.commit()

# --- FUNCIONES ORIGINALES DE GUARDADO (NO TOCAR) ---

def save_matches(matches_list):
    """Guarda los partidos finalizados en la BD."""
    with get_connection() as conn:
        c = conn.cursor()
        for m in matches_list:
            home_sets = m.get('sets', {}).get('home', 0)
            away_sets = m.get('sets', {}).get('away', 0)
            c.execute("""
                INSERT OR REPLACE INTO matches 
                (id, start_time, home, away, home_sets, away_sets, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (m.get('id'), m.get('start_time'), m.get('home'), m.get('away'), home_sets, away_sets, m.get('status')))
        conn.commit()

def save_players(elo_dict, stats_dict, last_played_dict):
    """Guarda las estadísticas y ELO de los jugadores."""
    with get_connection() as conn:
        c = conn.cursor()
        for player, elo in elo_dict.items():
            s = stats_dict.get(player, {})
            lp = last_played_dict.get(player, datetime.now().isoformat())
            c.execute("""
                INSERT OR REPLACE INTO players 
                (name, elo, wins, losses, matches, sets_won, sets_lost, last_played)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (player, int(elo), s.get('wins', 0), s.get('losses', 0), s.get('matches', 0), s.get('sets_won', 0), s.get('sets_lost', 0), lp))
        conn.commit()

def save_upcoming(upcoming_list):
    """Guarda la cartelera de próximos partidos."""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM upcoming")
        for m in upcoming_list:
            c.execute("""
                INSERT OR REPLACE INTO upcoming 
                (id, start_time, home, away)
                VALUES (?, ?, ?, ?)
            """, (m.get('id'), m.get('start_time'), m.get('home'), m.get('away')))
        conn.commit()

def save_odds(match_id, home_odd, away_odd):
    """Guarda las cuotas de Stake."""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO live_odds 
            (match_id, home_odd, away_odd, last_update)
            VALUES (?, ?, ?, ?)
        """, (match_id, home_odd, away_odd, datetime.now().isoformat()))
        conn.commit()

# --- NUEVAS FUNCIONES DE REFINAMIENTO (150 PARTIDOS & FATIGA) ---

def get_player_history(player_name, limit=150):
    """Obtiene el historial de un jugador específico. Límite ampliado a 150."""
    query = """
        SELECT * FROM matches 
        WHERE home = ? OR away = ? 
        ORDER BY start_time DESC LIMIT ?
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=(player_name, player_name, limit))

def get_h2h(player1, player2, limit=150):
    """Obtiene el historial directo (H2H) entre dos jugadores. Límite ampliado a 150."""
    query = """
        SELECT * FROM matches 
        WHERE (home = ? AND away = ?) OR (home = ? AND away = ?)
        ORDER BY start_time DESC LIMIT ?
    """
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=(player1, player2, player2, player1, limit))

def get_player_fatigue(player_name, hours=24):
    """Calcula cuántos partidos ha jugado el jugador en las últimas 24 horas."""
    time_threshold = (datetime.utcnow() - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    query = """
        SELECT COUNT(*) FROM matches 
        WHERE (home = ? OR away = ?) AND start_time >= ?
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (player_name, player_name, time_threshold))
        result = cursor.fetchone()
        return result[0] if result else 0