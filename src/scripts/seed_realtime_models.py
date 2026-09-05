"""
@fileoverview Seed-Skript - Realtime-Modelle fuer die Live-Transkription in MongoDB anlegen

@description
Die LLM-Konfigurationsmaske ordnet einem Use-Case nur Modelle zu, die in MongoDB
existieren und den Use-Case in ``use_cases`` fuehren. Dieses Skript legt die
realtime-faehigen Transkriptionsmodelle an bzw. ergaenzt bei bereits vorhandenen
Modellen den Use-Case ``live_transcription``.

Idempotent: mehrfaches Ausfuehren aendert nichts Zusaetzliches.

Aufruf:
    python -m src.scripts.seed_realtime_models

@module scripts.seed_realtime_models

@dependencies
- Internal: src.core.mongodb.llm_model_repository - Modell-Repository
- Internal: src.core.models.llm_models - LLMModel
- Internal: src.core.llm.use_cases - UseCase
"""

from typing import Any, Dict, List, Tuple

from src.core.llm.use_cases import UseCase
from src.core.models.llm_models import LLMModel
from src.core.mongodb.llm_model_repository import LLMModelRepository

PROVIDER = "openai"

# (Modellname, Beschreibung, Metadaten)
REALTIME_MODELS: List[Tuple[str, str, Dict[str, Any]]] = [
    (
        "gpt-4o-transcribe",
        "Live-Transkription mit hoher Genauigkeit",
        {"realtime": True, "turn_detection": True},
    ),
    (
        "gpt-4o-mini-transcribe",
        "Live-Transkription, schneller und guenstiger, etwas geringere Genauigkeit",
        {"realtime": True, "turn_detection": True},
    ),
    (
        "gpt-4o-transcribe-diarize",
        "Live-Transkription mit Sprecher-Erkennung (Sprecher-Labels je Abschnitt)",
        {"realtime": True, "turn_detection": True, "diarization": True},
    ),
    (
        "gpt-realtime-whisper",
        "Whisper in einer Realtime-Session; ohne serverseitige Sprechpausen-Erkennung",
        {"realtime": True, "turn_detection": False},
    ),
]

USE_CASE = UseCase.LIVE_TRANSCRIPTION.value


def seed() -> int:
    """Legt die Modelle an bzw. ergaenzt den Use-Case. Gibt die Zahl der Aenderungen zurueck."""
    repo = LLMModelRepository()
    changes = 0

    for model_name, description, metadata in REALTIME_MODELS:
        model_id = f"{PROVIDER}/{model_name}"
        existing = repo.get_model(model_id)

        if existing is None:
            repo.create_model(LLMModel(
                model_id=model_id,
                provider=PROVIDER,
                model_name=model_name,
                use_cases=[USE_CASE],
                enabled=True,
                description=description,
                metadata=metadata,
            ))
            print(f"angelegt: {model_id}")
            changes += 1
            continue

        if USE_CASE in existing.use_cases:
            print(f"unveraendert: {model_id}")
            continue

        merged_use_cases = [*existing.use_cases, USE_CASE]
        repo.update_model(model_id, {"use_cases": merged_use_cases})
        print(f"ergaenzt: {model_id} -> {merged_use_cases}")
        changes += 1

    return changes


if __name__ == "__main__":
    count = seed()
    print(f"Fertig. Geaenderte Modelle: {count}")
