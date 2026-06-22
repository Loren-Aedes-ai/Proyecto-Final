FROM python:3.10-slim

WORKDIR /app

# 1. INSTALAR DEPENDENCIAS DEL SISTEMA PARA AUDIO Y COMPILACIÓN
# build-essential y python3-dev garantizan que tensorflow-cpu se instale sin errores
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. INSTALAR DEPENDENCIAS DE PYTHON
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 3. COPIAR EL PROYECTO (Incluyendo tu main.py y mi_modelo_aedes.tflite)
COPY . .

# 4. ARRANCAR EL SERVIDOR
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501}"]