---
status: draft
last_verified: 2025-08-15
---

# Installation und Setup

## Systemvoraussetzungen

### Software
- Python 3.10+
- FFmpeg für Audio/Video-Verarbeitung
- Git
- Docker (optional)

### Hardware
- ≥ 4GB RAM
- ≥ 10GB Speicher

## Lokale Installation

```bash
git clone <repository-url>
cd CommonSecretaryServices
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
# source venv/bin/activate
pip install -r requirements.txt
```

## Konfiguration

### .env
```env
OPENAI_API_KEY=your-openai-key
YOUTUBE_API_KEY=your-youtube-key
DEBUG=True
```

### config/config.yaml (Ausschnitt)
```yaml
server:
  host: "127.0.0.1"
  port: 5000
  debug: true
```

## Start & Tests

```bash
# Server starten
python src/main.py

# API-Test (Audio)
curl -X POST \
  -H "Content-Type: multipart/form-data" \
  -F "file=@tests/samples/sample_audio.m4a" \
  http://localhost:5000/api/audio/process
```

## Docker (optional)

```bash
docker build -t secretary-services .
docker run -p 5000:5000 secretary-services
```
