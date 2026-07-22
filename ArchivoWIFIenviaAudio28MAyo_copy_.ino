#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_VL53L0X.h>
#include <driver/i2s.h>
#include <WiFiClientSecure.h>  // ← AGREGA ESTA LÍNEA

// --- CONFIGURACIÓN DE RED ---
const char* ssid     = "TIGO 54G 4E"; 
const char* password = "4801313";

//  
const char* serverUrl = "https://proyecto-final-production-df19.up.railway.app/predict"; 

Adafruit_VL53L0X sensor = Adafruit_VL53L0X();

#define SAMPLE_RATE 16000
#define RECORD_SECONDS 3
#define NUM_SAMPLES (SAMPLE_RATE * RECORD_SECONDS) // 16000 muestras para tu CNN

static int16_t audio_buffer[NUM_SAMPLES]; 

void setup() {
  Serial.begin(921600);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Conectando a Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi Conectado con éxito.");

  Wire.begin(8, 9);
  if (!sensor.begin()) { Serial.println("Error en VL53L0X"); while (1); }
  
  configurarI2S();
  Serial.println(">>> ESP32-S3 ENLAZADO  <<<");
}

void loop() {
  VL53L0X_RangingMeasurementData_t measure;
  sensor.rangingTest(&measure, false);

  // --- CAPA 1: Rango válido ampliado a 160 mm como pediste ---
  if (measure.RangeStatus != 4 && measure.RangeMilliMeter < 190) {

    // --- CAPA 2: Confirmación — toma 2 lecturas seguidas ---
    // Si las 3 confirman objeto cerca, es real. Si fue ruido, no se repite.
    int confirmaciones = 0;
    for (int i = 0; i < 2; i++) {
      VL53L0X_RangingMeasurementData_t confirmacion;
      sensor.rangingTest(&confirmacion, false);
      if (confirmacion.RangeStatus != 4 && confirmacion.RangeMilliMeter < 190) {
        confirmaciones++;
      }
    }

    // --- CAPA 3: Solo graba si 2 lecturas confirman el objeto ---
    if (confirmaciones >= 1) {
      Serial.print("Objeto CONFIRMADO a: ");
      Serial.print(measure.RangeMilliMeter);
      Serial.println(" mm. Iniciando grabación...");

      // 1. Declarar la variable ANTES de empezar el proceso
      unsigned long t_inicio_audio = millis(); 

      capturarAudio();
      unsigned long t_fin_audio = millis();
      unsigned long latencia_audio_ms = t_fin_audio - t_inicio_audio;
      // ===============================================

      // Imprimir la latencia calculada en la consola serie
      Serial.print(">>> Latencia de Audio (Captura + Envío): ");
      Serial.print(latencia_audio_ms);
      Serial.println(" ms");
      enviarAudioAlServidor(measure.RangeMilliMeter, latencia_audio_ms);
      delay(2000); // Pausa para evitar ráfagas repetidas
    } else {
      Serial.println("Lectura descartada — ruido del sensor.");
    }
  }
  delay(30);
}

void capturarAudio() {
  size_t bytesRead;
  int32_t sample32;
  int index = 0;

  while (index < NUM_SAMPLES) {
    i2s_read(I2S_NUM_0, &sample32, sizeof(sample32), &bytesRead, portMAX_DELAY);
    if (bytesRead > 0) {
      audio_buffer[index] = (int16_t)(sample32 >> 12);
      index++;
    }
  }
  Serial.println("Audio capturado.");
}

void enviarAudioAlServidor(int distancia,unsigned long latencia_audio_ms) {
  if (WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;

  http.begin(client, serverUrl);
  http.setTimeout(5000); // 10s es suficiente solo para el acknowledge
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);

  http.addHeader("Content-Type", "application/octet-stream");
  http.addHeader("X-Distance", String(distancia));
  http.addHeader("X-Timestamp-ESP32", String(millis()));
  http.addHeader("X-Latency-Audio-MS", String(latencia_audio_ms));

  size_t tamano = NUM_SAMPLES * sizeof(int16_t);
  int httpCode = http.POST((uint8_t*)audio_buffer, tamano);

  if (httpCode > 0) {
    String respuesta = http.getString();
    Serial.println("✔ Railway respondió: " + respuesta);
  } else {
    Serial.print("✘ Error: ");
    Serial.println(http.errorToString(httpCode).c_str());
  }
  http.end();
}
  
void configurarI2S() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 1024,
    .use_apll = false
  };
  i2s_pin_config_t pin_config = {
    .bck_io_num = 37, .ws_io_num = 36, .data_out_num = I2S_PIN_NO_CHANGE, .data_in_num = 35
  };
  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
}


