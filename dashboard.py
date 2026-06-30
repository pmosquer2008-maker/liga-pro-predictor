"""
dashboard.py — Terminal de Alta Probabilidad & Analytics (Pre-Match)
Diseño Institucional (UI/UX Premium) + Integración Refinada
"""

import streamlit as st
import pandas as pd
import json
import time
import os
from pathlib import Path
from datetime import datetime, timedelta
import db_manager

# Configuración de página a pantalla completa con icono
st.set_page_config(page_title="Liga Pro · Strike Engine", layout="wide", page_icon="⚡")

# ─── INYECCIÓN DE DISEÑO UI/UX (CSS) ───
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] { 
        font-family: 'Plus Jakarta Sans', sans-serif; 
    }
    
    /* Fondo principal y ocultar menús por defecto de Streamlit */
    .stApp { background-color: #0b1120; }
    
    /* Encabezados de fecha con degradado FinTech */
    .date-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #0f172a 100%);
        padding: 12px 24px; border-radius: 8px;
        color: #93c5fd; font-weight: 800; font-size: 1.15rem; margin-top: 25px; margin-bottom: 15px;
        border-left: 4px solid #3b82f6; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    
    /* Tarjetas de métricas tipo Glassmorphism */
    .metric-card {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid #334155; padding: 20px; border-radius: 12px;
        text-align: center; backdrop-filter: blur(10px); margin-bottom: 15px;
    }
    .metric-card h3 { color: #94a3b8; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
    .metric-card h2 { color: #f8fafc; font-size: 2rem; margin: 0; font-weight: 700; }
    
    /* Badges de Probabilidad */
    .high-prob { background-color: #064e3b; color: #34d399; padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 0.85em; border: 1px solid #059669; }
    .med-prob { background-color: #1e3a8a; color: #93c5fd; padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 0.85em; border: 1px solid #3b82f6; }
    .low-prob { background-color: #3f3f46; color: #d4d4d8; padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 0.85em; }
    
    /* Tarjetas de Kryptonita y Clientes */
    .kryptonite-card { background: linear-gradient(145deg, #450a0a 0%, #2e0505 100%); border: 1px solid #991b1b; padding: 20px; border-radius: 12px; }
    .hijos-card { background: linear-gradient(145deg, #022c22 0%, #011c16 100%); border: 1px solid #047857; padding: 20px; border-radius: 12px; }
    
    /* Tablas limpias */
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; padding: 12px; background-color: #1e293b; color: #94a3b8; font-weight: 600; font-size: 0.9rem; }
    td { padding: 12px; border-bottom: 1px solid #1e293b; color: #e2e8f0; font-size: 0.95rem; }
    tr:hover { background-color: #0f172a; }
</style>
""", unsafe_allow_html=True)

# ─── INICIALIZACIÓN BD Y FUNCIONES NÚCLEO ───
def init_bet_tracker():
    try:
        conn = db_manager.get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bet_history (
                fecha TEXT, partido TEXT, jugador_apostado TEXT, 
                cuota REAL, stake REAL, estado TEXT, ev_esperado REAL
            )
        ''')
        conn.commit()
    except: pass

init_bet_tracker()

def save_bet(partido, jugador, cuota, stake, ev):
    try:
        conn = db_manager.get_connection()
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute('''
            INSERT INTO bet_history (fecha, partido, jugador_apostado, cuota, stake, estado, ev_esperado)
            VALUES (?, ?, ?, ?, ?, 'Pendiente', ?)
        ''')
        conn.commit()
        st.toast("✅ Apuesta guardada exitosamente en el Tracker")
    except Exception as e:
        st.error(f"Error guardando apuesta: {e}")

def calculate_advanced_probability(p1, p2, elo_p1, elo_p2):
    """
    Función predictiva avanzada. 
    Integra ELO, H2H Dinámico (150 partidos) y Fatiga.
    """
    prob_base = 1 / (1 + 10 ** ((elo_p2 - elo_p1) / 400))
    
    h2h_data = db_manager.get_h2h(p1, p2, limit=150)
    p1_wins, p2_wins = 0, 0
    if not h2h_data.empty:
        for _, r in h2h_data.iterrows():
            if (r['home'] == p1 and r['home_sets'] > r['away_sets']) or (r['away'] == p1 and r['away_sets'] > r['home_sets']):
                p1_wins += 1
            else:
                p2_wins += 1
                
    total_h2h = p1_wins + p2_wins
    if total_h2h > 0:
        h2h_winrate = p1_wins / total_h2h
        prob_final = (prob_base * 0.7) + (h2h_winrate * 0.3)
    else:
        prob_final = prob_base
        
    fatiga_p1 = db_manager.get_player_fatigue(p1)
    fatiga_p2 = db_manager.get_player_fatigue(p2)
    
    if fatiga_p1 >= 4 and fatiga_p2 < 4:
        prob_final -= 0.05 
    elif fatiga_p2 >= 4 and fatiga_p1 < 4:
        prob_final += 0.05
        
    return max(0.01, min(0.99, prob_final)), p1_wins, p2_wins

def buscar_cuotas_flexibles(h_name, a_name, odds_map):
    """
    Motor de búsqueda flexible. Permite encontrar las cuotas de Stake
    incluso si Stake escribe los nombres al revés o con diferentes formatos.
    """
    m1 = f"{h_name}_{a_name}".replace(" ", "_")
    m2 = f"{a_name}_{h_name}".replace(" ", "_")
    if m1 in odds_map: return odds_map[m1]
    if m2 in odds_map: return odds_map[m2]
    
    h_words = [w.lower() for w in h_name.replace(',', '').split() if len(w) > 2]
    a_words = [w.lower() for w in a_name.replace(',', '').split() if len(w) > 2]
    
    for o_id, odds in odds_map.items():
        o_id_lower = o_id.lower().replace('_', ' ').replace('-', ' ')
        h_hit = any(w in o_id_lower for w in h_words)
        a_hit = any(w in o_id_lower for w in a_words)
        if h_hit and a_hit:
            return odds
            
    return None

# ─── BARRA LATERAL (ASISTENTE STAKE + COP) ───
st.sidebar.markdown("## 🎯 Asistente STAKE (Celular)")

# Enlace Directo a Stake Colombia
url_stake_liga_pro = "https://stake.com.co/deportes/table-tennis/world/czech-liga-pro"
st.sidebar.markdown(f"""
<a href="{url_stake_liga_pro}" target="_blank" style="text-decoration: none;">
    <button style="
        width: 100%;
        background-color: #1475e1;
        color: white;
        border: none;
        padding: 14px;
        font-weight: 800;
        border-radius: 8px;
        cursor: pointer;
        font-size: 16px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);">
        📱 ABRIR STAKE COLOMBIA
    </button>
</a>
""", unsafe_allow_html=True)

# Calculadora COP
st.sidebar.markdown("### 💰 Calculadora (COP)")
moneda_stake = st.sidebar.selectbox("Moneda Activa:", ["COP"])
valor_unidad = st.sidebar.number_input(f"Valor 1 Unidad (COP):", min_value=1000, value=10000, step=5000, format="%d")

def calcular_monto_real(multiplicador=1.0):
    return valor_unidad * multiplicador

st.sidebar.markdown("---")
st.sidebar.markdown("## ⚙️ Filtros del Motor")
timezone_offset = st.sidebar.number_input("Zona Horaria (UTC)", min_value=-12, max_value=14, value=-5, step=1)
seguridad_minima = st.sidebar.slider("Probabilidad Mínima (%)", 60, 95, 70, help="Filtra partidos riesgosos.")

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refrescar Pantalla", use_container_width=True):
    st.rerun()

# ─── ENCABEZADO PRINCIPAL ───
st.title("⚡ Strike Engine · Stake Edition")
st.markdown("<p style='color:#94a3b8; font-size:1.1rem; margin-top:-15px;'>Filtro algorítmico exclusivo para Mercado: <b>GANADOR DEL PARTIDO</b></p>", unsafe_allow_html=True)

# ─── ARQUITECTURA MULTI-PESTAÑA ───
tab_upcoming, tab_results, tab_analytics, tab_pnl = st.tabs([
    "🎯 Cartelera Stake & Análisis", 
    "🏆 Últimos Resultados",
    "📊 Jugadores & Analytics",
    "📒 Tracker (COP)"
])

# =====================================================================
# TAB 1: CARTELERA ENRIQUECIDA STAKE Y ANÁLISIS PROFUNDO
# =====================================================================
with tab_upcoming:
    try:
        conn = db_manager.get_connection()
        df_upcoming = pd.read_sql("SELECT * FROM upcoming", conn)
        df_odds = pd.read_sql("SELECT * FROM live_odds", conn)
        df_players = pd.read_sql("SELECT name, elo FROM players", conn)
        elo_dict = dict(zip(df_players.name, df_players.elo))
        
        if not df_upcoming.empty:
            odds_map = {}
            for _, row in df_odds.iterrows():
                odds_map[row['match_id']] = (row['home_odd'], row['away_odd'])
                
            if not odds_map:
                st.warning("⚠️ **ATENCIÓN:** Tu base de datos actual no tiene cuotas de Stake registradas. Para que los partidos aparezcan aquí, debes ejecutar el scraper en tu PC y actualizar el archivo `database.db` en GitHub.")
            
            cartelera = []
            partidos_activos_analisis = [] # Lista guardada para el selector de análisis
            partidos_sin_cuota = []
            
            for _, m in df_upcoming.iterrows():
                h_name, a_name = m["home"], m["away"]
                
                # Búsqueda Inteligente de Cuotas
                cuotas = buscar_cuotas_flexibles(h_name, a_name, odds_map)
                
                dt_local = None
                if m.get("start_time"):
                    try:
                        utc_time = datetime.fromisoformat(str(m["start_time"]).replace("Z", "+00:00"))
                        dt_local = utc_time + timedelta(hours=timezone_offset)
                    except: pass
                
                fecha_str = dt_local.strftime("%A, %d %b").capitalize() if dt_local else "Desconocido"
                hora_str = dt_local.strftime("%H:%M") if dt_local else "TBD"
                
                if not cuotas: 
                    partidos_sin_cuota.append({"Fecha": fecha_str, "Hora": hora_str, "Partido": f"{h_name} vs {a_name}"})
                    continue
                    
                cuota_h, cuota_a = cuotas
                elo_h = elo_dict.get(h_name, 1500)
                elo_a = elo_dict.get(a_name, 1500)
                
                prob_h, h2h_h, h2h_a = calculate_advanced_probability(h_name, a_name, elo_h, elo_a)
                prob_a = 1 - prob_h
                
                ev_h = (prob_h * cuota_h) - 1
                ev_a = (prob_a * cuota_a) - 1

                # Formato visual de probabilidad
                prob_h_str = f"<span style='color:{'#34d399' if prob_h > prob_a else '#94a3b8'}; font-weight:bold;'>{prob_h*100:.1f}%</span>"
                prob_a_str = f"<span style='color:{'#34d399' if prob_a > prob_h else '#94a3b8'}; font-weight:bold;'>{prob_a*100:.1f}%</span>"
                
                # Evaluador rápido visual
                if ev_h > 0 and (prob_h*100) >= seguridad_minima:
                    veredicto = f"<span class='high-prob'>🔥 Apostar a {h_name}</span>"
                elif ev_a > 0 and (prob_a*100) >= seguridad_minima:
                    veredicto = f"<span class='high-prob'>🔥 Apostar a {a_name}</span>"
                else:
                    veredicto = "<span class='low-prob'>Riesgo (Sin Valor)</span>"
                
                # Llenado de la Cartelera Principal (Mejorada)
                cartelera.append({
                    "Fecha": fecha_str,
                    "Hora": hora_str,
                    "Partido": f"<b>{h_name}</b> vs <b>{a_name}</b>",
                    "Prob. Modelo": f"{prob_h_str} vs {prob_a_str}",
                    "Cuotas (Stake)": f"<span style='color:#38bdf8'>{cuota_h}</span> | <span style='color:#38bdf8'>{cuota_a}</span>",
                    "H2H Histórico": f"{h2h_h} - {h2h_a}",
                    "Acción Recomendada": veredicto
                })
                
                # Guardar datos puros para la vista de Análisis Profundo
                partidos_activos_analisis.append({
                    "home": h_name, "away": a_name,
                    "cuota_h": cuota_h, "cuota_a": cuota_a,
                    "prob_h": prob_h, "prob_a": prob_a,
                    "ev_h": ev_h, "ev_a": ev_a,
                    "elo_h": elo_h, "elo_a": elo_a,
                    "h2h_h": h2h_h, "h2h_a": h2h_a
                })

            # --- 1. MOSTRAR CARTELERA COMPLETA (MEJORADA Y ÚNICA) ---
            st.markdown("<div class='date-header' style='background: linear-gradient(90deg, #064e3b 0%, #022c22 100%); border-left-color: #10b981;'>📅 Cartelera Activa en Stake (Mercados Abiertos)</div>", unsafe_allow_html=True)
            
            if cartelera:
                df_cartelera = pd.DataFrame(cartelera)
                for dia in df_cartelera['Fecha'].unique():
                    st.markdown(f"#### Programación: {dia}")
                    df_dia = df_cartelera[df_cartelera['Fecha'] == dia].drop(columns=['Fecha'])
                    st.markdown(df_dia.to_html(escape=False, index=False), unsafe_allow_html=True)
            elif odds_map:
                st.info("Hay cuotas en la base de datos, pero los nombres difieren drásticamente y no se pudieron enlazar. Verifica la ejecución del scraper.")
            
            # --- 2. MÓDULO INTERACTIVO DE ANÁLISIS PROFUNDO ---
            st.markdown("---")
            st.subheader("🔍 Análisis Profundo de Partido")
            st.caption("Selecciona cualquier partido de arriba para desgajar las matemáticas, ELO y fatiga antes de apostar.")
            
            opciones_partidos = ["Seleccionar partido..."] + [f"{p['home']} vs {p['away']}" for p in partidos_activos_analisis]
            seleccion = st.selectbox("Selecciona un juego vivo en Stake:", opciones_partidos)
            
            if seleccion != "Seleccionar partido...":
                p_data = next(p for p in partidos_activos_analisis if f"{p['home']} vs {p['away']}" == seleccion)
                
                # Extracción de fatiga para la vista profunda
                fatiga_h = db_manager.get_player_fatigue(p_data['home'])
                fatiga_a = db_manager.get_player_fatigue(p_data['away'])
                
                st.markdown(f"<h3 style='text-align:center; color:#f8fafc; margin-top:20px;'>{p_data['home']} vs {p_data['away']}</h3>", unsafe_allow_html=True)
                
                c1, c2 = st.columns(2)
                
                with c1:
                    is_fav = p_data['prob_h'] > p_data['prob_a']
                    st.markdown(f"""
                    <div class='metric-card' style='border-color: {"#3b82f6" if is_fav else "#334155"};'>
                        <h3>{p_data['home']} (Local)</h3>
                        <p style='margin-bottom:5px'><b>Prob. Modelo:</b> <span style='font-size:1.4rem; color:{"#34d399" if is_fav else "#94a3b8"};'>{p_data['prob_h']*100:.1f}%</span></p>
                        <p style='margin-bottom:5px'><b>Cuota Stake:</b> {p_data['cuota_h']}</p>
                        <p style='margin-bottom:5px'><b>Valor EV:</b> {'<span style="color:#34d399">+' + str(round(p_data['ev_h'],2)) + ' (Rentable)</span>' if p_data['ev_h'] > 0 else '<span style="color:#f87171">' + str(round(p_data['ev_h'],2)) + ' (No apostar)</span>'}</p>
                        <hr style='border-color:#334155'>
                        <p style='margin:0; font-size:0.9rem; color:#cbd5e1'>ELO: {int(p_data['elo_h'])} | Fatiga (24h): <b>{fatiga_h}</b> juegos</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                with c2:
                    is_fav_a = p_data['prob_a'] > p_data['prob_h']
                    st.markdown(f"""
                    <div class='metric-card' style='border-color: {"#3b82f6" if is_fav_a else "#334155"};'>
                        <h3>{p_data['away']} (Visitante)</h3>
                        <p style='margin-bottom:5px'><b>Prob. Modelo:</b> <span style='font-size:1.4rem; color:{"#34d399" if is_fav_a else "#94a3b8"};'>{p_data['prob_a']*100:.1f}%</span></p>
                        <p style='margin-bottom:5px'><b>Cuota Stake:</b> {p_data['cuota_a']}</p>
                        <p style='margin-bottom:5px'><b>Valor EV:</b> {'<span style="color:#34d399">+' + str(round(p_data['ev_a'],2)) + ' (Rentable)</span>' if p_data['ev_a'] > 0 else '<span style="color:#f87171">' + str(round(p_data['ev_a'],2)) + ' (No apostar)</span>'}</p>
                        <hr style='border-color:#334155'>
                        <p style='margin:0; font-size:0.9rem; color:#cbd5e1'>ELO: {int(p_data['elo_a'])} | Fatiga (24h): <b>{fatiga_a}</b> juegos</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.info(f"📊 **Contexto Histórico (Últimos 150):** {p_data['home']} ha ganado **{p_data['h2h_h']}** veces, mientras que {p_data['away']} ha ganado **{p_data['h2h_a']}** veces en enfrentamientos directos.")
                
                # Dictamen Final del Modelo
                if p_data['ev_h'] > 0 and (p_data['prob_h']*100) >= seguridad_minima:
                    st.success(f"🎯 **DICTAMEN DEL MODELO:** Apuesta altamente recomendada a **{p_data['home']}** a cuota {p_data['cuota_h']}. El modelo detecta una ventaja matemática superior a la casa de apuestas.")
                elif p_data['ev_a'] > 0 and (p_data['prob_a']*100) >= seguridad_minima:
                    st.success(f"🎯 **DICTAMEN DEL MODELO:** Apuesta altamente recomendada a **{p_data['away']}** a cuota {p_data['cuota_a']}. El modelo detecta una ventaja matemática superior a la casa de apuestas.")
                else:
                    st.warning("⛔ **DICTAMEN DEL MODELO:** Abstenerse de apostar. Ningún jugador ofrece un Valor Esperado (EV) positivo suficiente para arriesgar el capital con la seguridad actual.")

            # --- 3. MOSTRAR PARTIDOS HUÉRFANOS (Expander para que no estorbe) ---
            if partidos_sin_cuota:
                st.markdown("---")
                with st.expander("👀 Ver Partidos programados sin cuotas registradas aún"):
                    st.markdown("Estos partidos se acercan, pero la base de datos no tiene sus cuotas actualizadas desde Stake. Corre tu scraper para visualizarlos arriba.")
                    st.dataframe(pd.DataFrame(partidos_sin_cuota), hide_index=True, use_container_width=True)
                
        else:
            st.info("Esperando que el Scraper alimente la base de datos...")
    except Exception as e:
        st.error(f"Iniciando base de datos o procesando tabla: {e}")

# =====================================================================
# TAB 2: ÚLTIMOS RESULTADOS
# =====================================================================
with tab_results:
    st.markdown("### 🏆 Resultados Recientes")
    try:
        conn = db_manager.get_connection()
        df_recent = pd.read_sql("SELECT start_time, home, away, home_sets, away_sets FROM matches WHERE status='finalizado' ORDER BY start_time DESC LIMIT 20", conn)
        
        if not df_recent.empty:
            resultados = []
            for _, r in df_recent.iterrows():
                dt_local = datetime.fromisoformat(str(r["start_time"]).replace("Z", "+00:00")) + timedelta(hours=timezone_offset)
                
                h_name, a_name = r['home'], r['away']
                h_sets, a_sets = r['home_sets'], r['away_sets']
                
                if h_sets > a_sets:
                    h_disp = f"<span style='color:#34d399; font-weight:bold;'>{h_name}</span>"
                    a_disp = f"<span style='color:#94a3b8;'>{a_name}</span>"
                else:
                    h_disp = f"<span style='color:#94a3b8;'>{h_name}</span>"
                    a_disp = f"<span style='color:#34d399; font-weight:bold;'>{a_name}</span>"
                    
                resultados.append({
                    "Fecha": dt_local.strftime("%d %b - %H:%M"),
                    "Jugador Local": h_disp,
                    "Marcador": f"<b style='color:#f8fafc; font-size:1.1rem;'>{h_sets} - {a_sets}</b>",
                    "Jugador Visitante": a_disp
                })
            
            st.markdown(pd.DataFrame(resultados).to_html(escape=False, index=False), unsafe_allow_html=True)
        else:
            st.info("Aún no hay resultados históricos.")
    except:
        pass

# =====================================================================
# TAB 3: ANALYTICS & JUGADORES
# =====================================================================
with tab_analytics:
    try:
        conn = db_manager.get_connection()
        df_players = pd.read_sql("SELECT * FROM players ORDER BY elo DESC", conn)
        
        st.markdown("### 🕵️ Auditoría Específica de Jugador")
        busqueda = st.selectbox("Selecciona un jugador para auditar su perfil y némesis:", [""] + df_players['name'].tolist())
        
        if busqueda:
            jugador = df_players[df_players['name'] == busqueda].iloc[0]
            wr = (jugador['wins'] / jugador['matches'] * 100) if jugador['matches'] > 0 else 0
            
            st.markdown(f"""
            <div style="display:flex; gap:15px; margin-bottom:20px;">
                <div class="metric-card" style="flex:1;"><h3>Puntos ELO</h3><h2>{int(jugador['elo'])}</h2></div>
                <div class="metric-card" style="flex:1;"><h3>Win Rate</h3><h2>{wr:.1f}%</h2></div>
                <div class="metric-card" style="flex:1;"><h3>Partidos</h3><h2>{jugador['matches']}</h2></div>
                <div class="metric-card" style="flex:1;"><h3>Sets G/P</h3><h2>{jugador['sets_won']} / {jugador['sets_lost']}</h2></div>
            </div>
            """, unsafe_allow_html=True)
            
            df_historial = pd.read_sql(f"SELECT home, away, home_sets, away_sets FROM matches WHERE home='{busqueda}' OR away='{busqueda}'", conn)
            rivales = {}
            for _, r in df_historial.iterrows():
                is_home = (r['home'] == busqueda)
                rival = r['away'] if is_home else r['home']
                gana_jugador = (r['home_sets'] > r['away_sets']) if is_home else (r['away_sets'] > r['home_sets'])
                
                if rival not in rivales: rivales[rival] = {"pj": 0, "victorias": 0}
                rivales[rival]["pj"] += 1
                if gana_jugador: rivales[rival]["victorias"] += 1
                
            kryptonitas, para_apostar = [], []
            for rival, stats in rivales.items():
                win_ratio = stats["victorias"] / stats["pj"]
                if stats["pj"] >= 3 and win_ratio <= 0.25:
                    kryptonitas.append(f"<b>{rival}</b> (Perdió {stats['pj'] - stats['victorias']} de {stats['pj']} veces)")
                elif stats["pj"] >= 3 and win_ratio >= 0.80:
                    para_apostar.append(f"<b>{rival}</b> (Lo tiene de hijo: {stats['victorias']}/{stats['pj']} victorias)")
                    
            c_krypt, c_hijos = st.columns(2)
            with c_krypt:
                st.markdown("<div class='kryptonite-card'><h4 style='color:#fca5a5;margin-top:0'>☠️ KRYPTONITA (Evitar Apostar)</h4><hr style='border-color:#7f1d1d'>", unsafe_allow_html=True)
                if kryptonitas:
                    for k in kryptonitas: st.markdown(f"<p style='color:#fecaca; margin:5px 0;'>• {k}</p>", unsafe_allow_html=True)
                else: st.markdown("<p style='color:#fecaca'>No tiene rivales imposibles documentados.</p>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
                
            with c_hijos:
                st.markdown("<div class='hijos-card'><h4 style='color:#6ee7b7;margin-top:0'>💰 CLIENTES (Apostar Seguro)</h4><hr style='border-color:#047857'>", unsafe_allow_html=True)
                if para_apostar:
                    for p in para_apostar: st.markdown(f"<p style='color:#a7f3d0; margin:5px 0;'>• {p}</p>", unsafe_allow_html=True)
                else: st.markdown("<p style='color:#a7f3d0'>No tiene dominios aplastantes aún.</p>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
        
        st.divider()
        st.markdown("### 📋 Ranking General de Jugadores")
        df_players['Win Rate (%)'] = (df_players['wins'] / df_players['matches'] * 100).fillna(0)
        
        st.dataframe(
            df_players[['name', 'elo', 'Win Rate (%)', 'matches', 'wins', 'losses']],
            use_container_width=True,
            column_config={
                "name": "Jugador",
                "elo": st.column_config.ProgressColumn("Puntaje ELO", format="%d", min_value=1200, max_value=1800),
                "Win Rate (%)": st.column_config.NumberColumn("Efectividad", format="%.1f%%"),
                "matches": "PJ", "wins": "Victorias", "losses": "Derrotas"
            }
        )
            
    except Exception as e:
        st.error(f"Error analizando jugador: {e}")

# =====================================================================
# TAB 4: BET TRACKER & P&L (ACTUALIZADO A COP)
# =====================================================================
with tab_pnl:
    try:
        conn = db_manager.get_connection()
        df_bets = pd.read_sql("SELECT * FROM bet_history", conn)
        
        st.markdown("### 📒 Registro de Apuesta en COP")
        
        df_up = pd.read_sql("SELECT home, away FROM upcoming", conn)
        match_options = ["Seleccionar Partido..."] + [f"{r['home']} vs {r['away']}" for _, r in df_up.iterrows()]
        
        with st.container(border=True):
            col1, col2 = st.columns(2)
            with col1:
                selected_match = st.selectbox("1. Partido a apostar (Ganador)", match_options)
            
            if selected_match != "Seleccionar Partido...":
                p_home, p_away = selected_match.split(" vs ")
                
                with col2:
                    apostado_a = st.selectbox("2. ¿A quién le apuestas?", [p_home, p_away])
                
                col3, col4, col5 = st.columns([1,1,2])
                n_cuota = col3.number_input("3. Cuota Ofrecida", 1.01, step=0.1)
                n_stake = col4.number_input("4. Inversión (COP)", min_value=1000, value=int(valor_unidad), step=1000)
                
                df_p = pd.read_sql("SELECT name, elo FROM players", conn)
                elo_dict = dict(zip(df_p.name, df_p.elo))
                elo_h = elo_dict.get(p_home, 1500)
                elo_a = elo_dict.get(p_away, 1500)
                
                prob_h, _, _ = calculate_advanced_probability(p_home, p_away, elo_h, elo_a)
                prob_apostado = prob_h if apostado_a == p_home else (1 - prob_h)
                
                ev = (prob_apostado * n_cuota) - 1
                
                with col5:
                    st.markdown("<div style='padding-top:28px;'></div>", unsafe_allow_html=True)
                    if prob_apostado >= 0.70:
                        st.success(f"🔥 ¡Excelente elección! Probabilidad: **{prob_apostado*100:.1f}%** | EV: {ev:.2f}")
                    elif prob_apostado >= 0.55:
                        st.info(f"👍 Apuesta decente. Probabilidad: **{prob_apostado*100:.1f}%** | EV: {ev:.2f}")
                    else:
                        st.warning(f"⚠️ Alto Riesgo. Probabilidad baja (**{prob_apostado*100:.1f}%**). ¿Estás seguro?")
                
                if st.button("💾 Guardar Apuesta en el Tracker", type="primary", use_container_width=True):
                    save_bet(selected_match, apostado_a, n_cuota, n_stake, ev)
                    time.sleep(1)
                    st.rerun()

        st.divider()
        st.markdown("### 💰 Contabilidad General (P&L en COP)")
        
        if not df_bets.empty:
            df_resueltas = df_bets[df_bets['estado'].isin(['Ganada', 'Perdida'])]
            if not df_resueltas.empty:
                df_g = df_bets[df_bets['estado'] == 'Ganada']
                df_p = df_bets[df_bets['estado'] == 'Perdida']
                
                profit = sum(df_g['stake'] * (df_g['cuota'] - 1)) - sum(df_p['stake'])
                t_apostado = sum(df_resueltas['stake'])
                win_rate = (len(df_g) / len(df_resueltas)) * 100
                
                st.markdown(f"""
                <div style="display:flex; gap:15px; margin-bottom:20px;">
                    <div class="metric-card" style="flex:1;"><h3>Beneficio Neto (COP)</h3><h2 style="color:{'#34d399' if profit>=0 else '#f87171'}">${profit:,.0f}</h2></div>
                    <div class="metric-card" style="flex:1;"><h3>Total Invertido</h3><h2>${t_apostado:,.0f}</h2></div>
                    <div class="metric-card" style="flex:1;"><h3>Strike Rate (Acierto)</h3><h2 style="color:#60a5fa">{win_rate:.1f}%</h2></div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Resuelve algunas apuestas para ver tus métricas.")
            
            st.markdown("#### Auditar Apuestas")
            edited_df = st.data_editor(
                df_bets,
                column_config={
                    "estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "Ganada", "Perdida", "Anulada"]),
                    "stake": st.column_config.NumberColumn(format="$%d"),
                    "cuota": st.column_config.NumberColumn(format="%.2f"),
                },
                disabled=["fecha", "partido", "jugador_apostado", "ev_esperado"],
                use_container_width=True
            )
            if st.button("💾 Actualizar Historial Financiero"):
                edited_df.to_sql("bet_history", conn, if_exists="replace", index=False)
                st.success("¡Historial guardado exitosamente!")
                time.sleep(1)
                st.rerun()
    except Exception as e:
        st.error(f"Error cargando tracker: {e}")
