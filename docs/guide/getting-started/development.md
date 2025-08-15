---
status: draft
last_verified: 2025-08-15
---

# Entwicklung

## Umgebung
```powershell
venv\Scripts\activate
$env:PYTHONPATH = "."
python src/main.py
```

## Lint & Typen
```bash
ruff check .
mypy --config-file mypy.ini
```
- PEP8/Zeilenlänge ~100
- Strikte Type Hints, keine `Any` in öffentlichen APIs
- Docstrings im Google‑Format

## Async/Sync
- I/O/Netzwerk/API → async
- Reine Datenverarbeitung/Validierung → sync
- Wenn async aufgerufen wird → aufrufende Funktion ebenfalls async

## Tests
```bash
pytest -q
```
- Async‑Tests mit `@pytest.mark.asyncio`
- Coverage optional mit `pytest-cov`

## Git
- Commit‑Konventionen: feat/fix/docs/refactor/test
- Branches: `main` → `develop` → `feature/*`

## Beiträge & Support (Kurz)
- Issues/PRs über GitHub (Bugs, Features, Docs)
- Support per E‑Mail (siehe Support‑Seite)
