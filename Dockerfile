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
RUN mkdir -p logs temp-processing cache

# Umgebungsvariablen setzen
ENV PYTHONPATH=/app
ENV FLASK_APP=src.api:app
ENV FLASK_ENV=production

# Port exponieren
EXPOSE 5000

# Startbefehl
CMD ["flask", "run", "--host=0.0.0.0"] 