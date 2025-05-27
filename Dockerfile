FROM python:3.12.1-slim

# System-Abhängigkeiten installieren
RUN apt-get update && apt-get install -y \
    libmagic1 \
    ffmpeg \
    tesseract-ocr \
    poppler-utils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis setzen
WORKDIR /app

# requirements.txt kopieren und Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installiere die neueste Version von yt-dlp
RUN pip install --no-cache-dir --upgrade yt-dlp

# Projektcode kopieren
COPY . .

# Verzeichnisse erstellen
RUN mkdir -p logs temp-processing cache config

# Umgebungsvariablen setzen
ENV PYTHONPATH=/app
ENV FLASK_APP=src.main:app
ENV FLASK_ENV=production
ENV FLASK_DEBUG=0



# Port exponieren
EXPOSE 5001

# Startbefehl
CMD ["python", "-m", "src.main"] 