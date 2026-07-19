import os
import json
import time
import pytz
import wave
import librosa
import threading
import numpy as np
import tensorflow as tf
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
import uvicorn
from scipy.signal import butter, lfilter
from contextlib import asynccontextmanager
import traceback
import base64

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
# --- 2. GOOGLE SHEETS (datos) + GOOGLE DRIVE (audios .wav) ---
# ==============================================================================
GOOGLE_SHEETS_ID        = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_SHEETS_CREDS_B64 = os.getenv("GOOGLE_SHEETS_CREDS_B64")
GOOGLE_SHEETS_TAB       = os.getenv("GOOGLE_SHEETS_TAB", "Registros")
GOOGLE_DRIVE_FOLDER_ID  = os.getenv("GOOGLE_DRIVE_FOLDER_ID")  # carpeta donde se guardan los .wav

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

SHEET_HEADERS = [
    "Evento", "Fecha", "Hora", "Distancia (mm)",
    "Frecuencia (Hz)", "Amplitud (dB)", "Probabilidad (%)",
    "Armónicos", "Latencia Red (ms)", "Latencia CNN (ms)", "Alerta"
]

gs_client      = None
gs_worksheet   = None
drive_service  = None
gs_lock        = threading.Lock()  # gspread no es thread-safe, protegemos escrituras

print("DEBUG GOOGLE_SHEETS_ID       :", GOOGLE_SHEETS_ID)
print("DEBUG GOOGLE_SHEETS_TAB      :", GOOGLE_SHEETS_TAB)
print("DEBUG GOOGLE_DRIVE_FOLDER_ID :", GOOGLE_DRIVE_FOLDER_ID)

if not all([GOOGLE_SHEETS_ID, GOOGLE_SHEETS_CREDS_B64]):
    raise ValueError("❌ Faltan variables de Google Sheets en el entorno del servidor "
                      "(GOOGLE_SHEETS_ID / GOOGLE_SHEETS_CREDS_B64).")

if not GOOGLE_DRIVE_FOLDER_ID:
    print("  ⚠️ GOOGLE_DRIVE_FOLDER_ID no configurado: los .wav no se subirán a Drive "
          "(solo se guardarán los datos en Sheets).")


def iniciar_google_apis():
    """Autentica una sola vez con la cuenta de servicio y deja listos Sheets y Drive."""
    global gs_client, gs_worksheet, drive_service

    creds_json = base64.b64decode(GOOGLE_SHEETS_CREDS_B64).decode("utf-8")
    creds_dict = json.loads(creds_json)
    creds      = Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SCOPES)

    # --- Sheets ---
    gs_client = gspread.authorize(creds)
    sh = gs_client.open_by_key(GOOGLE_SHEETS_ID)

    try:
        gs_worksheet = sh.worksheet(GOOGLE_SHEETS_TAB)
    except gspread.WorksheetNotFound:
        gs_worksheet = sh.add_worksheet(title=GOOGLE_SHEETS_TAB, rows=2000, cols=len(SHEET_HEADERS) + 2)

    primera_fila = gs_worksheet.row_values(1)
    if primera_fila != SHEET_HEADERS:
        gs_worksheet.resize(rows=max(gs_worksheet.row_count, 2))
        gs_worksheet.update("A1", [SHEET_HEADERS])

    print(f"  ✅ Google Sheets conectado → tab '{GOOGLE_SHEETS_TAB}'")

    # --- Drive ---
    drive_service = build("drive", "v3", credentials=creds)
    print("  ✅ Google Drive conectado")


def guardar_en_google_sheets(fila: list):
    """Agrega una fila de evento a la hoja de Google Sheets, con reintentos."""
    if gs_worksheet is None:
        raise RuntimeError("Google Sheets no está inicializado.")

    fila_str = [str(x) for x in fila]

    ultimo_error = None
    for intento in range(3):
        try:
            with gs_lock:
                gs_worksheet.append_row(fila_str, value_input_option="USER_ENTERED")
            return
        except Exception as e:
            ultimo_error = e
            print(f"  ⚠️ Intento {intento + 1}/3 falló escribiendo en Sheets: {e}")
            time.sleep(1.5 * (intento + 1))

    raise RuntimeError(f"No se pudo escribir en Google Sheets tras 3 intentos: {ultimo_error}")


def subir_wav_a_google_drive(ruta_wav: str, nombre_archivo: str):
    """Sube el .wav a la carpeta de Google Drive configurada (reemplaza a GitHub)."""
    if drive_service is None or not GOOGLE_DRIVE_FOLDER_ID:
        return

    try:
        metadata = {
            "name": nombre_archivo,
            "parents": [GOOGLE_DRIVE_FOLDER_ID],
        }
        media  = MediaFileUpload(ruta_wav, mimetype="audio/wav", resumable=False)
        result = drive_service.files().create(body=metadata, media_body=media, fields="id").execute()
        print(f"  🎵 WAV subido a Google Drive: {nombre_archivo} (id={result.get('id')})")
    except Exception as e:
        print(f"  ❌ Error subiendo WAV a Google Drive: {e}")


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
            guardar_en_google_sheets(fila)
            print(f"✅ Fila guardada correctamente en Google Sheets")
        except Exception as e:
            print(f"❌ Error guardando en Google Sheets: {type(e).__name__}: {e}")
            traceback.print_exc()

        subir_wav_a_google_drive(ruta_wav, nombre_archivo)

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

    print("🚀 Conectando a Google Sheets y Google Drive...")
    iniciar_google_apis()

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