FROM python:3.11-slim

# System-Abhängigkeiten installieren
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis setzen
WORKDIR /app

# requirements.txt kopieren und Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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