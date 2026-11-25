# Basisimage python:3.12-slim, per Digest gepinnt (Stand 10.11.2026), damit jeder Build dasselbe
# Image verwendet. Aktualisieren: docs/deployment/abhaengigkeiten.md
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# System-Abhängigkeiten installieren; apt-get upgrade holt Sicherheitsupdates, die seit dem
# Stand des Basisimages erschienen sind
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    libmagic1 \
    ffmpeg \
    tesseract-ocr \
    poppler-utils \
    python3-pip \
    # WeasyPrint (job_type booklet): Pango, HarfBuzz-Subsetting, Fallback-Schrift
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# JS-Laufzeit für yt-dlp: ohne sie löst yt-dlp YouTubes JS-Challenges nicht, und angemeldete
# Abrufe finden keine Formate. Deno ist die von yt-dlp vorgesehene Laufzeit (mindestens 2.3.0);
# das Debian-Paket nodejs ist dafür zu alt (yt-dlp verlangt Node ab v22). Eine einzelne Datei
# aus dem offiziellen Image, per Digest gepinnt (Stand 25.11.2026). Aktualisieren:
# docs/deployment/abhaengigkeiten.md
COPY --from=denoland/deno:bin-2.9.8@sha256:b507583d3c68ba69f3ed2ce5969ae5b8b70f43421c781279c7aea06435263543 /deno /usr/local/bin/deno
RUN deno --version

# Arbeitsverzeichnis setzen
WORKDIR /app

# Abhängigkeiten aus dem Lockfile installieren: jede Version ist gepinnt und per Hash geprüft.
# Kein nachträgliches "pip install --upgrade": yt-dlp und alle anderen Pakete werden bewusst
# über requirements.txt und requirements.lock angehoben (docs/deployment/abhaengigkeiten.md).
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary=pillow -r requirements.lock

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