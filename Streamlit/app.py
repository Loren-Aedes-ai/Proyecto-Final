import streamlit as st
import pandas as pd
import glob
import os
import re
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh  # <-- Importante ponerlo aquí
import requests
import io


# ==============================================================================
# --- CONFIGURACIÓN DE LA PÁGINA ---
# ==============================================================================
st.set_page_config(page_title="Dashboard Monitor Aedes", layout="wide", page_icon="🦟")

st.markdown("""
    <style>
    .main-title { font-size:38px !important; font-weight: bold; color: #2E4053; margin-bottom: 5px; }
    .subtitle { font-size:18px !important; color: #5D6D7E; margin-bottom: 25px; }
    </style>
    """, unsafe_allow_html=True)

st.markdown('<p class="main-title">📊 Sistema de Monitoreo Biológico - Aedes aegypti</p>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Análisis de datos acústicos e inferencia de IA en tiempo real</p>', unsafe_allow_html=True)

# ==============================================================================
# --- CARGA Y PROCESAMIENTO DESDE GITHUB ---
# ==============================================================================
@st.cache_data(ttl=30)
def cargar_datos_reportes():
    import requests
    import io
    from datetime import datetime, timedelta

    USUARIO  = "Loren-Aedes-ai"
    REPO     = "Proyecto-Final"
    RAMA     = "main"
    CARPETA  = "datos/excel"

    lista_dfs = []

    # Intenta los últimos 7 días
    for dias_atras in range(7):
        fecha = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
        nombre_archivo = f"reporte_{fecha}.xlsx"
        url = f"https://raw.githubusercontent.com/{USUARIO}/{REPO}/{RAMA}/{CARPETA}/{nombre_archivo}"

        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                continue

            # Intentamos leer el Excel
            df = pd.read_excel(io.BytesIO(response.content), engine="openpyxl")
            
            # Agregar columnas de fecha y mes
            df['Fecha_Registro'] = pd.to_datetime(fecha)
            df['Mes'] = df['Fecha_Registro'].dt.strftime('%Y-%m ( %B )')

            ## 🛠️ MAPEO CORREGIDO SEGÚN TU EXCEL: Cambiado 'Frecuencia Central' por 'Frecuencia (Hz)'
            df['Frec_Num'] = pd.to_numeric(df['Frecuencia (Hz)'], errors='coerce').fillna(0)
            df['Amp_Num']  = pd.to_numeric(df['Amplitud (dB)'],    errors='coerce').fillna(0)
            df['Prob_Num'] = pd.to_numeric(df['Probabilidad (%)'], errors='coerce').fillna(0) / 100.0
            df['Dist_Num'] = pd.to_numeric(df['Distancia (mm)'],   errors='coerce').fillna(0)
            lista_dfs.append(df)
            print(f"✅ Cargado: {nombre_archivo} ({len(df)} registros)")

        except Exception as e:
            continue

    if lista_dfs:
        return pd.concat(lista_dfs, ignore_index=True)
    return pd.DataFrame()

df_global = cargar_datos_reportes()

if df_global.empty:
    st.warning("⚠️ No se encontraron reportes recientes en GitHub. Verifica que Railway esté activo.")
    st.stop()


# ==============================================================================
# --- FILTROS LATERALES ---
# ==============================================================================
st.sidebar.header("🎛️ Filtros Globales")
lista_meses = sorted(df_global['Mes'].unique())
mes_seleccionado = st.sidebar.selectbox("Seleccionar Mes de Análisis:", ["Todos los meses"] + lista_meses)

# Filtrado del DataFrame objetivo
if mes_seleccionado != "Todos los meses":
    df_filtrado = df_global[df_global['Mes'] == mes_seleccionado]
else:
    df_filtrado = df_global

# ==============================================================================
# --- FILA 1: TARJETAS DE MÉTRICAS CLAVE (KPIs) ---
# ==============================================================================
total_detecciones = len(df_filtrado)
positivos_aedes = len(df_filtrado[df_filtrado['Prob_Num'] > 0.5])
freq_promedio = df_filtrado['Frec_Num'].mean() if total_detecciones > 0 else 0
amp_promedio = df_filtrado['Amp_Num'].mean() if total_detecciones > 0 else 0

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    st.metric(label="🎙️ Total Eventos Capturados", value=f"{total_detecciones}")
with kpi2:
    st.metric(label="🦟 Positivos Aedes (IA > 50%)", value=f"{positivos_aedes}", delta=f"{(positivos_aedes/total_detecciones if total_detecciones>0 else 0):.1%} del total", delta_color="inverse")
with kpi3:
    st.metric(label="🎼 Frecuencia Fundamental Promedio", value=f"{freq_promedio:.1f} Hz")
with kpi4:
    st.metric(label="🔊 Presión Sonora Promedio", value=f"{amp_promedio:.1f} dB")

st.markdown("---")

# ==============================================================================
# --- FILA 2: GRÁFICOS Y MAPA GEOGRÁFICO ---
# ==============================================================================
col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.subheader("📍 Ubicación Geográfica del Sensor")
    
    # Coordenadas proporcionadas (Campus Central USAC, Zona 12)
    lat_sensor = 14.58849
    lon_sensor = -90.5533
    
    # Generación del mapa interactivo usando capas de OpenStreetMap
    m = folium.Map(location=[lat_sensor, lon_sensor], zoom_start=17, tiles="OpenStreetMap")
    
    # Marcador estilizado para representar el dispositivo físico
    popup_text = f"""
    <div style='font-family: Arial, sans-serif; width: 180px;'>
        <h4 style='margin:0 0 5px 0; color:#C0392B;'>Dispositivo IoT #1</h4>
        <b>Estado:</b> Activo Escuchando<br>
        <b>Muestras Mes:</b> {total_detecciones}<br>
        <b>Positivos:</b> {positivos_aedes}<br>
        <small style='color:gray;'>Lat: {lat_sensor}<br>Lon: {lon_sensor}</small>
    </div>
    """
    
    folium.Marker(
        [lat_sensor, lon_sensor],
        popup=folium.Popup(popup_text, max_width=250),
        tooltip="Dispositivo de Monitoreo Biológico",
        icon=folium.Icon(color="red", icon="microchip", prefix="fa")
    ).add_to(m)
    
    # Renderizado del mapa en Streamlit
    st_folium(m, width="100%", height=380, returned_objects=[])

with col_der:
    st.subheader("📈 Histórico Evolutivo / Tendencia Mensual")
    
    # Agrupación por fecha/mes para ver la evolución temporal del insecto
    df_mensual = df_global.groupby('Mes').agg(
        Total_Eventos=('Evento', 'count'),
        Positivos_Aedes=('Prob_Num', lambda x: (x > 0.5).sum())
    ).reset_index()
    
    fig_lineas = go.Figure()
    fig_lineas.add_trace(go.Bar(
        x=df_mensual['Mes'], y=df_mensual['Total_Eventos'],
        name='Total Ruidos Capturados', marker_color='#AED6F1'
    ))
    fig_lineas.add_trace(go.Scatter(
        x=df_mensual['Mes'], y=df_mensual['Positivos_Aedes'],
        name='Casos Confirmados Aedes', mode='lines+markers',
        line=dict(color='#E74C3C', width=3), marker=dict(size=8)
    ))
    
    fig_lineas.update_layout(
        margin=dict(l=20, r=20, t=20, b=20),
        height=380, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        barmode='group', plot_bgcolor='white'
    )
    fig_lineas.update_yaxes(gridcolor='#F2F4F4')
    st.plotly_chart(fig_lineas, use_container_width=True)

# ==============================================================================
# --- FILA 3: ANÁLISIS ESPECTRAL Y TABLA DE DATOS CRUDOS ---
# ==============================================================================
st.markdown("---")
col_analisis_1, col_analisis_2 = st.columns([4, 6])


with col_analisis_1:

    st.subheader("🦟 Clasificación de Alertas por Nivel de Confianza")
    
    # Clasificar los eventos en categorías fáciles de leer
    def clasificar_alerta(prob):
        if prob >= 0.75:
            return "🔴 ALTA (Aedes Confirmado)"
        elif prob >= 0.40:
             return "🟡 MEDIA (Mosquito Sospechoso)"
        else:
            return "🟢 BAJA (Ruido Ambiental / Descartado)"
            
    df_filtrado['Categoria_Alerta'] = df_filtrado['Prob_Num'].apply(clasificar_alerta)
    
    # Contar cuántos hay en cada categoría
    conteo_alertas = df_filtrado['Categoria_Alerta'].value_counts().reset_index()
    conteo_alertas.columns = ['Nivel de Alerta', 'Cantidad de Audios']
    
    # Crear un gráfico de barras simple con colores de semáforo
    colores_semaforo = {
        "🔴 ALTA (Aedes Confirmado)": "#E74C3C",
        "🟡 MEDIA (Mosquito Sospechoso)": "#F4D03F",
        "🟢 BAJA (Ruido Ambiental / Descartado)": "#2ECC71"
    }
    
    fig_barras_facil = px.bar(
        conteo_alertas,
        x='Nivel de Alerta',
         y='Cantidad de Audios',
        color='Nivel de Alerta',
        color_discrete_map=colores_semaforo,
        text_auto=True
    )
    
    fig_barras_facil.update_layout(
        height=350,
        margin=dict(l=10, r=10, t=10, b=10),
         plot_bgcolor='white',
        showlegend=False
    )
    fig_barras_facil.update_yaxes(gridcolor='#F2F4F4')
    st.plotly_chart(fig_barras_facil, use_container_width=True)


with col_analisis_2:
    st.subheader("📋 Registros de Detecciones Filtrados")
        
    #  1. Definimos la lista con los nombres NUEVOS y reales de tus columnas
    columnas_mostrar = ['Evento', 'Fecha', 'Hora', 'Distancia (mm)', 'Frecuencia (Hz)', 'Amplitud (dB)', 'Probabilidad (%)', 'Alerta']
    
    if not df_filtrado.empty:
        # 2. Aquí se genera la nueva línea df_tabla reemplazando por completo la vieja
        df_tabla = df_filtrado[columnas_mostrar].copy()
        
        # 3. Mostramos la tabla limpia en la pantalla de Streamlit
        st.dataframe(df_tabla, use_container_width=True, height=350)
    else:
        st.info("No hay registros para mostrar bajo el filtro seleccionado.")
