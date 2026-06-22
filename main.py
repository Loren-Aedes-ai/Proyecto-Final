import os
import io
from io import BytesIO
import time
import pytz
import wave
import librosa
import requests
import threading
import numpy as np
import tensorflow as tf
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
import uvicorn
from scipy.signal import butter, lfilter
from contextlib import asynccontextmanager
import traceback
import openpyxl
import base64
from pathlib import Path

# ==============================================================================
# --- 1. CONFIGURACIÓN GLOBAL ---
# ==============================================================================
API_PORT       = int(os.environ.get("PORT", 8080))
SAMPLE_RATE    = 16000
RECORD_SECONDS = 3
OUTPUT_DIR     = os.path.join(os.getcwd(), "audios_temp")
FACTOR_AMP     = 10.0
MODEL_PATH     = 'mi_modelo_aedes.tflite'

# Variables globales para el intérprete TFLite
interpreter    = None
input_details  = None
output_details = None

os.makedirs(OUTPUT_DIR, exist_ok=True)

contador_evento = 1

# ==============================================================================
# --- 2. EXCEL EN GITHUB ---
# ==============================================================================
import requests as req_github

GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN")
GITHUB_USER      = os.getenv("GITHUB_USER")
GITHUB_REPO      = os.getenv("GITHUB_REPO")
GITHUB_PATH_BASE = "datos/excel"

print("DEBUG TOKEN:", GITHUB_TOKEN)
print("DEBUG USER :", GITHUB_USER)
print("DEBUG REPO :", GITHUB_REPO)
print("DEBUG PATH_BASE:", GITHUB_PATH_BASE)

if not all([GITHUB_TOKEN, GITHUB_USER, GITHUB_REPO]):
    raise ValueError("❌ Faltan variables GitHub en el entorno del servidor.")

EXCEL_HEADERS = [
    "Evento", "Fecha", "Hora", "Distancia (mm)",
    "Frecuencia (Hz)", "Amplitud (dB)", "Probabilidad (%)",
    "Armónicos", "Latencia Red (ms)", "Latencia CNN (ms)", "Alerta"
]


def guardar_en_excel_local(fila: list):
    """Descarga el Excel del día actual de GitHub, agrega la fila y lo vuelve a subir."""
    if not GITHUB_TOKEN or not GITHUB_USER or not GITHUB_REPO:
        raise ValueError("❌ Faltan variables GitHub.")

    try:
        headers_gh = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        zona_guatemala = pytz.timezone("America/Guatemala")
        fecha_hoy      = datetime.now(zona_guatemala).strftime("%Y-%m-%d")
        nombre_excel   = f"reporte_{fecha_hoy}.xlsx"
        ruta_github_archivo = f"{GITHUB_PATH_BASE}/{nombre_excel}"
        url_archivo = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{ruta_github_archivo}"

        response = req_github.get(url_archivo, headers=headers_gh)
        sha = None

        if response.status_code == 200:
            data      = response.json()
            sha       = data["sha"]
            contenido = base64.b64decode(data["content"])
            wb        = openpyxl.load_workbook(BytesIO(contenido))
            ws        = wb.active
            print(f"  📥 Excel del día ({nombre_excel}) descargado de GitHub.")
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Registros Aedes"
            ws.append(EXCEL_HEADERS)
            print(f"  📄 Creando nuevo Excel para el día de hoy: {nombre_excel}")

        ws.append(fila)

        buffer        = BytesIO()
        wb.save(buffer)
        contenido_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        payload = {
            "message": f"Evento #{fila[0]} registrado en {nombre_excel}",
            "content": contenido_b64
        }
        if sha:
            payload["sha"] = sha

        put_response = req_github.put(url_archivo, headers=headers_gh, json=payload)

        if put_response.status_code in [200, 201]:
            print(f"  ✅ Excel guardado exitosamente en: {ruta_github_archivo}")
        else:
            print(f"  ❌ GitHub respondió {put_response.status_code}: {put_response.text}")

    except Exception as e:
        print(f"  ❌ Error al guardar Excel en GitHub: {e}")
        traceback.print_exc()


def subir_wav_a_github(ruta_wav: str, nombre_archivo: str):
    """Sube el archivo .wav a GitHub en la carpeta audios/"""
    if not all([GITHUB_TOKEN, GITHUB_USER, GITHUB_REPO]):
        print("⚠️ Faltan variables GitHub para subir WAV.")
        return

    try:
        with open(ruta_wav, "rb") as f:
            contenido_b64 = base64.b64encode(f.read()).decode("utf-8")

        fecha_hoy   = datetime.now().strftime("%Y-%m-%d")
        ruta_github = f"audios/{fecha_hoy}/{nombre_archivo}"
        url         = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{ruta_github}"

        headers_gh = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "message": f"Audio {nombre_archivo}",
            "content": contenido_b64
        }

        response = req_github.put(url, headers=headers_gh, json=payload)
        if response.status_code in [200, 201]:
            print(f"  🎵 WAV subido a GitHub: {ruta_github}")
        else:
            print(f"  ❌ Error subiendo WAV: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Error subiendo WAV a GitHub: {e}")


# ==============================================================================
# --- 3. FUNCIONES DE AUDIO Y PROCESAMIENTO CNN ---
# ==============================================================================
def filtro_pasa_alta(data, sr):
    cutoff = 300
    nyq    = 0.5 * sr
    normal_cutoff = cutoff / nyq
    if normal_cutoff >= 1:
        return data
    b, a = butter(6, normal_cutoff, btype='high', analog=False)
    return lfilter(b, a, data)


def procesar_audio_aedes(y, sr):
    y_filtrado = filtro_pasa_alta(y, sr)
    if np.max(np.abs(y_filtrado)) > 0:
        return librosa.util.normalize(y_filtrado)
    return y_filtrado


def analizar_mosquito(file_path, model=None):
    try:
        time.sleep(0.05)

        y_raw, sr = librosa.load(file_path, sr=None)

        if len(y_raw) == 0:
            print("⚠️ El archivo de audio llegó vacío.")
            return 0.0, 0.0, -80.0, "No detectados"

        rms         = librosa.feature.rms(y=y_raw)
        rms_medio   = np.mean(rms)
        amplitud_db = 20 * np.log10(rms_medio) if rms_medio > 0 else -80.0

        y = procesar_audio_aedes(y_raw, sr)

        S      = np.abs(librosa.stft(y))
        f      = librosa.fft_frequencies(sr=sr)
        S_mean = np.mean(S, axis=1)

        mask = (f >= 200) & (f <= 2000)
        if np.any(mask):
            f_sub          = f[mask]
            S_sub          = S_mean[mask]
            freq_dominante = f_sub[np.argmax(S_sub)]

            armonicos_detectados = []
            for i in [2, 3, 4]:
                target_freq = freq_dominante * i
                if target_freq < (sr / 2):
                    mask_arm  = (f >= (target_freq - 50)) & (f <= (target_freq + 50))
                    if np.any(mask_arm):
                        freq_real = f[mask_arm][np.argmax(S_mean[mask_arm])]
                        armonicos_detectados.append(f"{freq_real:.1f} Hz")
                    else:
                        armonicos_detectados.append(f"~{target_freq:.1f} Hz")
                else:
                    armonicos_detectados.append("N/A")
            str_armonicos = " | ".join(armonicos_detectados)
        else:
            freq_dominante = 0.0
            str_armonicos  = "No detectados"

        mel_spec    = librosa.feature.melspectrogram(y=y, sr=sr, fmin=200, fmax=2000, n_mels=128)
        mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)

        img = tf.image.resize(mel_spec_db[..., np.newaxis], (128, 128)).numpy()
        if (np.max(img) - np.min(img)) != 0:
            img = (img - np.min(img)) / (np.max(img) - np.min(img))

        input_data = np.expand_dims(img, axis=0).astype(np.float32)

        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        pred = interpreter.get_tensor(output_details[0]['index'])

        probabilidad = float(pred.flatten()[0]) if isinstance(pred, np.ndarray) else float(pred)

        TOLERANCIA_ARM = 60.0
        if freq_dominante < 340.0 or freq_dominante > 660.0:
            probabilidad = 0.0
        else:
            armonicos_validos = 0
            for i in [2, 3, 4]:
                target = freq_dominante * i
                if target < (sr / 2):
                    mask_arm = (f >= (target - TOLERANCIA_ARM)) & (f <= (target + TOLERANCIA_ARM))
                    if np.any(mask_arm) and np.max(S_mean[mask_arm]) > np.mean(S_mean) * 1.5:
                        armonicos_validos += 1

            if armonicos_validos >= 2:
                probabilidad = max(probabilidad, 0.70)
                print(f"  ✅ Armónicos validados ({armonicos_validos}/3) → prob ajustada: {probabilidad:.2%}")
            else:
                if probabilidad < 0.30:
                    probabilidad = 0.0

        return probabilidad, freq_dominante, amplitud_db, str_armonicos

    except Exception as e:
        print(f"\n❌ [ERROR EN IA / AUDIO]: {e}")
        return 0.0, 0.0, -80.0, "Error en procesamiento"


# ==============================================================================
# --- 4. PROCESAMIENTO EN SEGUNDO PLANO ---
# ==============================================================================
def procesar_audio_e_inferencia(raw_audio, distancia_mm, hora_detectada,
                                timestamp_file, ts_llegada, latencia_red_ms):
    global contador_evento

    zona_guatemala = pytz.timezone("America/Guatemala")
    ahora          = datetime.now(zona_guatemala)
    hora_detectada = ahora.strftime("%H:%M:%S")
    timestamp_file = ahora.strftime("%Y%m%d_%H%M%S")

    nombre_archivo = f'audio_{timestamp_file}.wav'
    prob, freq, amp_db, armonicos = 0.0, 0.0, 0.0, "N/A"
    latencia_cnn = 0

    try:
        ts_inicio_cnn = int(time.time() * 1000)

        samples  = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
        samples *= FACTOR_AMP
        samples  = np.clip(samples, -32768, 32767).astype(np.int16)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ruta_wav = os.path.join(OUTPUT_DIR, nombre_archivo)

        with wave.open(ruta_wav, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(samples.tobytes())

        prob, freq, amp_db, armonicos = analizar_mosquito(ruta_wav)

        ts_fin_cnn   = int(time.time() * 1000)
        latencia_cnn = ts_fin_cnn - ts_inicio_cnn
        latencia_total = latencia_cnn + max(latencia_red_ms, 0)

        alerta = "🚨 SÍ" if prob > 0.65 else "No"
        fila = [
            contador_evento,
            ahora.strftime("%Y-%m-%d"),
            hora_detectada,
            distancia_mm,
            round(freq, 2),
            round(amp_db, 2),
            round(prob * 100, 2),
            armonicos,
            latencia_red_ms,
            latencia_cnn,
            alerta
        ]

        sep = "─" * 65
        print(f"\n{sep}")
        print(f"📊 EVENTO #{contador_evento} PROCESADO  [{hora_detectada}]")
        print(f"{sep}")
        print(f"  Archivo Registrado : {nombre_archivo}")
        print(f"  Distancia Objetivo : {distancia_mm} mm")
        print(f"  Frecuencia Alateo  : {freq:.2f} Hz")
        print(f"  Intensidad Sonido  : {amp_db:.2f} dB")
        print(f"  Espectro Armónicos : {armonicos}")
        print(f"  Probabilidad Aedes : {prob:.2%}")
        print(f"  ⏱  Latencia Red    : {latencia_red_ms} ms")
        print(f"  ⏱  Latencia CNN    : {latencia_cnn} ms")
        print(f"  ⏱  Latencia Total  : {latencia_total} ms")
        print(f"{sep}\n")

        try:
            guardar_en_excel_local(fila)
            print(f"✅ Excel guardado correctamente en GitHub")
        except Exception as e:
            print(f"❌ Error guardando Excel en GitHub: {type(e).__name__}: {e}")
            traceback.print_exc()

        subir_wav_a_github(ruta_wav, nombre_archivo)

        if os.path.exists(ruta_wav):
            os.remove(ruta_wav)

        contador_evento += 1

    except Exception as e:
        print("💥 ERROR CRÍTICO EN SEGUNDO PLANO:")
        traceback.print_exc()


# ==============================================================================
# --- 5. SERVIDOR FASTAPI ---
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global interpreter, input_details, output_details
    print("🚀 Iniciando Servidor... Cargando motor TFLite.")

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"❌ No se encontró '{MODEL_PATH}'.")

    interpreter = tf.lite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details  = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    print("✅ Motor TFLite listo.")
    yield
    print("🛑 Servidor apagado.")


app = FastAPI(lifespan=lifespan)


@app.post("/predict")
async def recibir_audio_wifi(request: Request, background_tasks: BackgroundTasks):
    try:
        raw_audio = await request.body()

        timestamp_llegada = int(time.time() * 1000)
        distancia_mm      = request.headers.get("X-Distance", "?")
        latencia_audio    = request.headers.get("X-Latency-Audio-MS")

        ahora          = datetime.now()
        hora_detectada = ahora.strftime("%H:%M:%S")
        timestamp_file = ahora.strftime("%Y%m%d_%H%M%S")

        try:
            latencia_ms = int(latencia_audio)
        except:
            latencia_ms = -1

        print(f"📡 Audio recibido [{hora_detectada}] — Distancia: {distancia_mm}mm — Latencia: {latencia_ms}ms")

        background_tasks.add_task(
            procesar_audio_e_inferencia,
            raw_audio, distancia_mm, hora_detectada,
            timestamp_file, timestamp_llegada, latencia_ms
        )

        return {"status": "recibido", "hora": hora_detectada, "latencia": f"{latencia_ms}ms"}

    except Exception as e:
        print(f"❌ Error en endpoint: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=puerto)
