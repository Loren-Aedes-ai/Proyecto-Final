import streamlit as st
import pandas as pd
import requests
import io
import time
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURACIÓN — cambia solo estas dos líneas
# ─────────────────────────────────────────────
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Loren-Arq/mi_proyecto_esp32/main/datos/excel/reporte_2026-06-14.xlsx"
REFRESH_SECONDS = 30  # actualiza cada 30 segundos
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Monitor Aedes aegypti",
    page_icon="🦟",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Estilos ──────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .main { background-color: #0f1117; }

    /* Header */
    .header-box {
        background: linear-gradient(135deg, #1a1f2e 0%, #0d1b2a 100%);
        border: 1px solid #1e3a5f;
        border-radius: 12px;
        padding: 24px 32px;
        margin-bottom: 24px;
        display: flex;
        align-items: center;
        gap: 16px;
    }
    .header-title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #e8f4fd;
        margin: 0;
        letter-spacing: -0.5px;
    }
    .header-sub {
        font-size: 0.85rem;
        color: #5a8fa8;
        margin: 4px 0 0 0;
        font-family: 'JetBrains Mono', monospace;
    }

    /* KPI cards */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 16px;
        margin-bottom: 24px;
    }
    .kpi-card {
        background: #1a1f2e;
        border: 1px solid #1e3a5f;
        border-radius: 10px;
        padding: 20px 24px;
        position: relative;
        overflow: hidden;
    }
    .kpi-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: var(--accent);
    }
    .kpi-label {
        font-size: 0.72rem;
        font-weight: 600;
        color: #5a8fa8;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .kpi-value {
        font-size: 2rem;
        font-weight: 700;
        color: #e8f4fd;
        font-family: 'JetBrains Mono', monospace;
        line-height: 1;
    }
    .kpi-unit {
        font-size: 0.9rem;
        color: #5a8fa8;
        margin-left: 4px;
    }
    .kpi-delta {
        font-size: 0.78rem;
        margin-top: 6px;
        color: #5a8fa8;
    }
    .kpi-delta.positive { color: #4caf82; }
    .kpi-delta.warning  { color: #e8a84c; }
    .kpi-delta.danger   { color: #e85c5c; }

    /* Alert badge */
    .badge-aedes {
        display: inline-block;
        background: #3d1a1a;
        border: 1px solid #e85c5c;
        color: #e85c5c;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 0.72rem;
        font-weight: 600;
    }
    .badge-ok {
        display: inline-block;
        background: #1a3d2b;
        border: 1px solid #4caf82;
        color: #4caf82;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 0.72rem;
        font-weight: 600;
    }

    /* Section title */
    .section-title {
        font-size: 0.78rem;
        font-weight: 600;
        color: #5a8fa8;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        margin: 0 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #1e3a5f;
    }

    /* Last update */
    .last-update {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        color: #3d5a6e;
        text-align: right;
        margin-bottom: 8px;
    }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)


# ── Carga de datos ────────────────────────────
@st.cache_data(ttl=REFRESH_SECONDS)
def cargar_datos(url: str) -> pd.DataFrame:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl")
        # Normalizar nombres de columnas
        df.columns = df.columns.str.strip()
        # Crear columna datetime combinada
        if "Fecha" in df.columns and "Hora" in df.columns:
            df["Datetime"] = pd.to_datetime(
                df["Fecha"].astype(str) + " " + df["Hora"].astype(str),
                errors="coerce"
            )
        return df
    except Exception as e:
        return None, str(e)


# ── Header ───────────────────────────────────
st.markdown("""
<div class="header-box">
    <span style="font-size:2.2rem">🦟</span>
    <div>
        <p class="header-title">Sistema de Monitoreo Biológico — <em>Aedes aegypti</em></p>
        <p class="header-sub">Detección acústica · CNN en tiempo real · ESP32-S3 + INMP441</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Auto-refresh ─────────────────────────────
placeholder_update = st.empty()
df = cargar_datos(GITHUB_RAW_URL)

if df is None or (isinstance(df, tuple)):
    st.error("⚠️ No se pudo cargar el archivo Excel desde GitHub. Verifica la URL en GITHUB_RAW_URL.")
    st.stop()

ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
placeholder_update.markdown(f'<p class="last-update">Última actualización: {ahora} · refresca cada {REFRESH_SECONDS}s</p>', unsafe_allow_html=True)

# ── Métricas ──────────────────────────────────
total_eventos   = len(df)
col_alerta      = "Alerta" if "Alerta" in df.columns else None
positivos       = int(df[col_alerta].astype(str).str.upper().str.contains("AEDES|SÍ|SI|YES|1|TRUE").sum()) if col_alerta else 0
pct_positivos   = round(positivos / total_eventos * 100, 1) if total_eventos > 0 else 0
freq_prom       = round(df["Frecuencia (Hz)"].mean(), 1) if "Frecuencia (Hz)" in df.columns else 0
amp_prom        = round(df["Amplitud (dB)"].mean(), 1) if "Amplitud (dB)" in df.columns else 0
prob_prom       = round(df["Probabilidad (%)"].mean(), 1) if "Probabilidad (%)" in df.columns else 0
dist_prom       = round(df["Distancia (mm)"].mean(), 1) if "Distancia (mm)" in df.columns else 0

delta_class_pos = "danger" if pct_positivos > 50 else ("warning" if pct_positivos > 25 else "positive")

st.markdown(f"""
<div class="kpi-grid">
  <div class="kpi-card" style="--accent:#4c8fe8;">
    <p class="kpi-label">📡 Total Eventos</p>
    <p class="kpi-value">{total_eventos}</p>
    <p class="kpi-delta">registros en Excel</p>
  </div>
  <div class="kpi-card" style="--accent:#e85c5c;">
    <p class="kpi-label">🦟 Positivos Aedes</p>
    <p class="kpi-value">{positivos}</p>
    <p class="kpi-delta {delta_class_pos}">▲ {pct_positivos}% del total</p>
  </div>
  <div class="kpi-card" style="--accent:#4caf82;">
    <p class="kpi-label">🎵 Frecuencia Promedio</p>
    <p class="kpi-value">{freq_prom}<span class="kpi-unit">Hz</span></p>
    <p class="kpi-delta">rango objetivo 380–620 Hz</p>
  </div>
  <div class="kpi-card" style="--accent:#e8a84c;">
    <p class="kpi-label">🔊 Amplitud Promedio</p>
    <p class="kpi-value">{amp_prom}<span class="kpi-unit">dB</span></p>
    <p class="kpi-delta">Probabilidad CNN: {prob_prom}%</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Gráficas ──────────────────────────────────
PLOTLY_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,17,23,0.6)",
    font=dict(family="Inter, sans-serif", color="#7a9ab8", size=12),
    margin=dict(l=10, r=10, t=36, b=10),
    xaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
    yaxis=dict(gridcolor="#1e3a5f", linecolor="#1e3a5f", zeroline=False),
)

col1, col2 = st.columns(2)

# ── Gráfica 1: Probabilidad CNN en el tiempo
with col1:
    st.markdown('<p class="section-title">📈 Probabilidad CNN por Evento</p>', unsafe_allow_html=True)
    if "Probabilidad (%)" in df.columns:
        x_axis = df["Datetime"] if "Datetime" in df.columns else df["Evento"]
        colores = ["#e85c5c" if v >= 75 else "#4c8fe8" for v in df["Probabilidad (%)"]]
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(
            x=x_axis, y=df["Probabilidad (%)"],
            mode="lines+markers",
            line=dict(color="#4c8fe8", width=2),
            marker=dict(color=colores, size=8, line=dict(color="#0f1117", width=1)),
            fill="tozeroy",
            fillcolor="rgba(76,143,232,0.08)",
            name="Probabilidad CNN",
            hovertemplate="<b>%{y:.1f}%</b><extra></extra>"
        ))
        fig1.add_hline(y=75, line_dash="dash", line_color="#e85c5c",
                       annotation_text="Umbral 75%", annotation_font_color="#e85c5c")
        fig1.update_layout(**PLOTLY_THEME, height=280,
                           yaxis=dict(**PLOTLY_THEME["yaxis"], range=[0, 105]))
        st.plotly_chart(fig1, use_container_width=True)

# ── Gráfica 2: Frecuencia por evento
with col2:
    st.markdown('<p class="section-title">🎵 Frecuencia Fundamental por Evento</p>', unsafe_allow_html=True)
    if "Frecuencia (Hz)" in df.columns:
        x_axis = df["Datetime"] if "Datetime" in df.columns else df["Evento"]
        colores_freq = ["#4caf82" if 380 <= v <= 620 else "#e8a84c" for v in df["Frecuencia (Hz)"]]
        fig2 = go.Figure()
        fig2.add_hrect(y0=380, y1=620, fillcolor="rgba(76,175,130,0.07)",
                       line_width=0, annotation_text="Zona Aedes (380–620 Hz)",
                       annotation_font_color="#4caf82", annotation_font_size=10)
        fig2.add_trace(go.Scatter(
            x=x_axis, y=df["Frecuencia (Hz)"],
            mode="lines+markers",
            line=dict(color="#4caf82", width=2),
            marker=dict(color=colores_freq, size=8, line=dict(color="#0f1117", width=1)),
            name="Frecuencia Hz",
            hovertemplate="<b>%{y:.0f} Hz</b><extra></extra>"
        ))
        fig2.update_layout(**PLOTLY_THEME, height=280)
        st.plotly_chart(fig2, use_container_width=True)

col3, col4 = st.columns(2)

# ── Gráfica 3: Distancia sensor
with col3:
    st.markdown('<p class="section-title">📏 Distancia Sensor VL53L0X</p>', unsafe_allow_html=True)
    if "Distancia (mm)" in df.columns:
        x_axis = df["Datetime"] if "Datetime" in df.columns else df["Evento"]
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            x=x_axis, y=df["Distancia (mm)"],
            marker_color="#7c5ce8",
            marker_line_color="#0f1117",
            marker_line_width=1,
            name="Distancia mm",
            hovertemplate="<b>%{y:.0f} mm</b><extra></extra>"
        ))
        fig3.update_layout(**PLOTLY_THEME, height=260)
        st.plotly_chart(fig3, use_container_width=True)

# ── Gráfica 4: Distribución alertas (pie)
with col4:
    st.markdown('<p class="section-title">🎯 Distribución de Alertas</p>', unsafe_allow_html=True)
    if col_alerta:
        counts = df[col_alerta].value_counts()
        fig4 = go.Figure(go.Pie(
            labels=counts.index,
            values=counts.values,
            hole=0.55,
            marker=dict(colors=["#e85c5c", "#4c8fe8", "#4caf82"],
                        line=dict(color="#0f1117", width=2)),
            textfont=dict(color="#e8f4fd"),
            hovertemplate="<b>%{label}</b>: %{value} eventos<extra></extra>"
        ))
        fig4.update_layout(**PLOTLY_THEME, height=260,
                           legend=dict(font=dict(color="#7a9ab8")),
                           annotations=[dict(text=f"<b>{total_eventos}</b><br>eventos",
                                            x=0.5, y=0.5, font_size=14,
                                            font_color="#e8f4fd", showarrow=False)])
        st.plotly_chart(fig4, use_container_width=True)

# ── Gráfica 5: Latencia CNN vs Red
st.markdown('<p class="section-title">⚡ Latencia del Sistema (CNN vs Red)</p>', unsafe_allow_html=True)
if "Latencia CNN (ms)" in df.columns and "Latencia Red (ms)" in df.columns:
    x_axis = df["Datetime"] if "Datetime" in df.columns else df["Evento"]
    fig5 = go.Figure()
    fig5.add_trace(go.Scatter(
        x=x_axis, y=df["Latencia CNN (ms)"],
        name="CNN", mode="lines+markers",
        line=dict(color="#e8a84c", width=2),
        marker=dict(size=6),
        hovertemplate="CNN: <b>%{y:.0f} ms</b><extra></extra>"
    ))
    fig5.add_trace(go.Scatter(
        x=x_axis, y=df["Latencia Red (ms)"],
        name="Red", mode="lines+markers",
        line=dict(color="#7c5ce8", width=2),
        marker=dict(size=6),
        hovertemplate="Red: <b>%{y:.0f} ms</b><extra></extra>"
    ))
    fig5.update_layout(**PLOTLY_THEME, height=220,
                       legend=dict(orientation="h", y=1.1, font=dict(color="#7a9ab8")))
    st.plotly_chart(fig5, use_container_width=True)

# ── Tabla últimos eventos ─────────────────────
st.markdown('<p class="section-title">📋 Últimos 10 Eventos</p>', unsafe_allow_html=True)

df_show = df.tail(10).copy()
if "Datetime" in df_show.columns:
    df_show = df_show.drop(columns=["Datetime"], errors="ignore")

def colorear_alerta(val):
    val_str = str(val).upper()
    if any(k in val_str for k in ["AEDES", "SÍ", "SI", "YES", "1", "TRUE"]):
        return "background-color:#3d1a1a; color:#e85c5c; font-weight:600"
    return "background-color:#1a3d2b; color:#4caf82; font-weight:600"

styled = df_show.style.applymap(colorear_alerta, subset=["Alerta"]) if "Alerta" in df_show.columns else df_show.style
st.dataframe(styled, use_container_width=True, height=300)

# ── Auto-refresh real ─────────────────────────
st.markdown("---")
col_r1, col_r2 = st.columns([3, 1])
with col_r1:
    st.markdown(f'<p style="color:#3d5a6e; font-size:0.75rem; font-family: monospace;">🔄 Datos desde GitHub · Excel actualizado por Railway · refresh cada {REFRESH_SECONDS}s</p>', unsafe_allow_html=True)
with col_r2:
    if st.button("🔄 Actualizar ahora"):
        st.cache_data.clear()
        st.rerun()

# Auto-rerun silencioso
time.sleep(REFRESH_SECONDS)
st.rerun()