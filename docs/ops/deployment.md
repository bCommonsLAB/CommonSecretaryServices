---
status: draft
last_verified: 2025-08-15
---

# Deployment

## Lokal
```powershell
venv\Scripts\activate
$env:PYTHONPATH = "."
python src/main.py
```

## Docker
```bash
docker build -t secretary-services .
docker run -p 5000:5000 secretary-services
```

## Compose
```yaml
services:
  api:
    build: .
    ports: ["5000:5000"]
    env_file: .env
```

## Gesundheit & Tests
```bash
pytest -q
curl http://localhost:5000/api/doc
```
