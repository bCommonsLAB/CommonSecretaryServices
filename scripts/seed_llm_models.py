#!/usr/bin/env python3
"""
Legt die Transkriptions-Modelle in MongoDB an, damit die LLM-Konfigurationsmaske sie
je Use-Case zur Auswahl anbietet.

Eigenstaendig: braucht nur ``pymongo`` und eine MongoDB-URI. Anders als
``src/scripts/seed_realtime_models.py`` laedt dieses Skript NICHT den Projekt-Code
(und damit nicht PyMuPDF, pydub, yt-dlp ...) — es laeuft deshalb auch ausserhalb des
Containers, etwa lokal auf einem Rechner ohne die Systemabhaengigkeiten.

Hintergrund: Die Maske ordnet einem Use-Case nur Modelle zu, die in der Collection
``llm_models`` existieren und den Use-Case in ``use_cases`` fuehren. Ohne diese
Dokumente bleibt die Auswahlliste leer.

Aufruf:
    python scripts/seed_llm_models.py --dry-run     # nur zeigen, was passieren wuerde
    python scripts/seed_llm_models.py               # anlegen bzw. ergaenzen

Die URI kommt aus ``MONGODB_URI`` oder aus ``--uri``. Der Datenbankname wird der URI
entnommen (so macht es auch der Dienst); fehlt er dort, hilft ``--db``.

Das Skript ist idempotent: bestehende Modelle werden nicht ueberschrieben, es werden
nur fehlende Use-Cases ergaenzt.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple

PROVIDER = "openai"

# Use-Case-Namen wie in src/core/llm/use_cases.py
USE_CASE_FILE = "transcription"
USE_CASE_LIVE = "live_transcription"


class ModelDefinition(NamedTuple):
    """Ein Modell und die Use-Cases, fuer die es taugt."""

    name: str
    use_cases: List[str]
    description: str
    metadata: Dict[str, Any]


# Stand der Anbieter-Dokumentation (September 2026).
#
# Wichtig bei der Zuordnung:
# - 'gpt-4o-transcribe-diarize' liefert Sprecher-Labels, aber NUR bei der
#   Datei-Transkription. Es gehoert deshalb nicht zu 'live_transcription'.
# - 'gpt-live-transcribe' ist das empfohlene Modell fuer Live-Sessions,
#   'gpt-transcribe' das empfohlene fuer Dateien.
# - 'whisper-1' ist das einzige Modell mit Wort-Zeitstempeln und SRT/VTT.
MODELS: List[ModelDefinition] = [
    ModelDefinition(
        name="gpt-transcribe",
        use_cases=[USE_CASE_FILE],
        description="Empfohlen fuer Dateien: hohe Genauigkeit, nimmt keywords und mehrere Sprachen",
        metadata={"empfohlen_fuer": "datei", "keywords": True, "sprachliste": True},
    ),
    ModelDefinition(
        name="gpt-live-transcribe",
        use_cases=[USE_CASE_LIVE],
        description="Empfohlen fuer Live-Sessions: Text waehrend des Sprechens",
        metadata={"empfohlen_fuer": "live", "keywords": True, "sprachliste": True, "realtime": True},
    ),
    ModelDefinition(
        name="gpt-4o-transcribe",
        use_cases=[USE_CASE_FILE, USE_CASE_LIVE],
        description="Vorgaenger-Generation, laeuft auf beiden Wegen",
        metadata={"realtime": True},
    ),
    ModelDefinition(
        name="gpt-4o-mini-transcribe",
        use_cases=[USE_CASE_FILE, USE_CASE_LIVE],
        description="Kleiner und guenstiger, etwas geringere Genauigkeit",
        metadata={"realtime": True},
    ),
    ModelDefinition(
        name="gpt-4o-transcribe-diarize",
        use_cases=[USE_CASE_FILE],
        description="Sprecher-Labels (nur Datei-Transkription, kein Freitext-Kontext)",
        metadata={"diarisierung": True, "prompt": False},
    ),
    ModelDefinition(
        name="gpt-realtime-whisper",
        use_cases=[USE_CASE_LIVE],
        description="Whisper in einer Live-Session, ohne serverseitige Sprechpausen-Erkennung",
        metadata={"realtime": True, "sprechpausen_erkennung": False},
    ),
    ModelDefinition(
        name="whisper-1",
        use_cases=[USE_CASE_FILE],
        description="Einziges Modell mit Wort-Zeitstempeln und SRT/VTT",
        metadata={"zeitstempel": True, "untertitel": True},
    ),
]


def open_collection(uri: str, db_name: str | None) -> Any:
    """Oeffnet die Collection 'llm_models'."""
    try:
        from pymongo import MongoClient
    except ImportError:
        print("Fehler: pymongo fehlt. Installieren mit:  pip install pymongo", file=sys.stderr)
        raise SystemExit(2)

    client: Any = MongoClient(uri, serverSelectionTimeoutMS=10000)
    if db_name:
        database = client[db_name]
    else:
        try:
            database = client.get_default_database()
        except Exception:
            print(
                "Fehler: Die MONGODB_URI nennt keinen Datenbanknamen.\n"
                "Entweder in die URI aufnehmen (…mongodb.net/DEINE_DB?retryWrites=true)\n"
                "oder beim Aufruf angeben:  --db DEINE_DB",
                file=sys.stderr,
            )
            raise SystemExit(2)

    # Frueh scheitern, wenn die Datenbank nicht erreichbar ist — sonst laeuft das
    # Skript scheinbar durch und schreibt nichts.
    client.admin.command("ping")
    print(f"Verbunden mit Datenbank: {database.name}")
    return database.llm_models


def seed(collection: Any, dry_run: bool) -> int:
    """Legt die Modelle an bzw. ergaenzt fehlende Use-Cases. Gibt die Zahl der Aenderungen zurueck."""
    changes = 0
    now = datetime.now(timezone.utc)

    for definition in MODELS:
        model_id = f"{PROVIDER}/{definition.name}"
        existing = collection.find_one({"model_id": model_id})

        if existing is None:
            document = {
                "model_id": model_id,
                "provider": PROVIDER,
                "model_name": definition.name,
                "use_cases": list(definition.use_cases),
                "enabled": True,
                "description": definition.description,
                "metadata": dict(definition.metadata),
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            if dry_run:
                print(f"  [wuerde anlegen]  {model_id}  ({', '.join(definition.use_cases)})")
            else:
                collection.insert_one(document)
                print(f"  angelegt          {model_id}  ({', '.join(definition.use_cases)})")
            changes += 1
            continue

        current: List[str] = list(existing.get("use_cases") or [])
        missing = [use_case for use_case in definition.use_cases if use_case not in current]
        if not missing:
            print(f"  unveraendert      {model_id}")
            continue

        merged = current + missing
        if dry_run:
            print(f"  [wuerde ergaenzen] {model_id}  +{', '.join(missing)}")
        else:
            collection.update_one(
                {"model_id": model_id},
                {"$set": {"use_cases": merged, "updated_at": now.isoformat()}},
            )
            print(f"  ergaenzt          {model_id}  +{', '.join(missing)}")
        changes += 1

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Legt die Transkriptions-Modelle fuer die LLM-Konfigurationsmaske an."
    )
    parser.add_argument("--uri", default=os.getenv("MONGODB_URI"), help="MongoDB-URI (sonst MONGODB_URI)")
    parser.add_argument("--db", default=None, help="Datenbankname, falls die URI keinen nennt")
    parser.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts schreiben")
    args = parser.parse_args()

    if not args.uri:
        print("Fehler: Keine MongoDB-URI. Setze MONGODB_URI oder nutze --uri", file=sys.stderr)
        return 2

    collection = open_collection(args.uri, args.db)
    print("Trockenlauf — es wird nichts geschrieben.\n" if args.dry_run else "")
    changes = seed(collection, args.dry_run)

    print(f"\nFertig. {'Zu aendern' if args.dry_run else 'Geaendert'}: {changes} von {len(MODELS)} Modellen.")
    if not args.dry_run and changes:
        print(
            "\nNaechster Schritt: In der LLM-Konfigurationsmaske je Use-Case ein Modell waehlen —\n"
            "  Transcription (Audio/Video)        -> gpt-transcribe\n"
            "  Live-Transcription (Realtime)      -> gpt-live-transcribe"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
