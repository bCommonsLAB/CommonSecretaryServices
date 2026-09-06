"""Tests fuer das eigenstaendige Seed-Skript.

Geprueft wird die Zuordnung der Modelle zu den Use-Cases und die Idempotenz: ein
zweiter Lauf darf nichts mehr aendern, und bestehende Modelle duerfen nicht
ueberschrieben, sondern nur um fehlende Use-Cases ergaenzt werden.
"""

import importlib.util
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

# Das Skript liegt bewusst ausserhalb des Pakets (es soll ohne Projekt-Import laufen),
# deshalb wird es hier direkt ueber seinen Pfad geladen.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_llm_models.py"
_spec = importlib.util.spec_from_file_location("seed_llm_models", _SCRIPT)
assert _spec and _spec.loader
seed_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_module)


class FakeCollection:
    """Minimale Nachbildung der Mongo-Collection fuer die Seed-Logik."""

    def __init__(self, documents: Optional[List[Dict[str, Any]]] = None) -> None:
        self.documents: List[Dict[str, Any]] = documents or []

    def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for document in self.documents:
            if document.get("model_id") == query.get("model_id"):
                return document
        return None

    def insert_one(self, document: Dict[str, Any]) -> None:
        self.documents.append(document)

    def update_one(self, query: Dict[str, Any], update: Dict[str, Any]) -> None:
        document = self.find_one(query)
        if document is not None:
            document.update(update["$set"])


class TestCatalogue(unittest.TestCase):
    """Die Zuordnung der Modelle zu den Use-Cases."""

    def test_diarize_model_is_file_only(self) -> None:
        # Sprecher-Labels gibt es laut Anbieter nur bei der Datei-Transkription.
        diarize = next(m for m in seed_module.MODELS if m.name == "gpt-4o-transcribe-diarize")

        self.assertIn(seed_module.USE_CASE_FILE, diarize.use_cases)
        self.assertNotIn(seed_module.USE_CASE_LIVE, diarize.use_cases)

    def test_recommended_models_are_present(self) -> None:
        by_name = {m.name: m for m in seed_module.MODELS}

        self.assertEqual(by_name["gpt-transcribe"].use_cases, [seed_module.USE_CASE_FILE])
        self.assertEqual(by_name["gpt-live-transcribe"].use_cases, [seed_module.USE_CASE_LIVE])

    def test_every_model_has_at_least_one_use_case(self) -> None:
        for model in seed_module.MODELS:
            self.assertTrue(model.use_cases, f"{model.name} ohne Use-Case")


class TestSeeding(unittest.TestCase):
    """Anlegen, Ergaenzen, Wiederholen."""

    def test_creates_all_models_on_empty_database(self) -> None:
        collection = FakeCollection()

        changes = seed_module.seed(collection, dry_run=False)

        self.assertEqual(changes, len(seed_module.MODELS))
        self.assertEqual(len(collection.documents), len(seed_module.MODELS))
        self.assertTrue(all(d["provider"] == "openai" for d in collection.documents))
        self.assertTrue(all(d["model_id"].startswith("openai/") for d in collection.documents))

    def test_second_run_changes_nothing(self) -> None:
        collection = FakeCollection()
        seed_module.seed(collection, dry_run=False)

        changes = seed_module.seed(collection, dry_run=False)

        self.assertEqual(changes, 0)
        self.assertEqual(len(collection.documents), len(seed_module.MODELS))

    def test_adds_missing_use_case_without_overwriting(self) -> None:
        # Ein bestehendes Modell mit eigener Beschreibung und nur einem Use-Case.
        collection = FakeCollection([
            {
                "model_id": "openai/gpt-4o-transcribe",
                "provider": "openai",
                "model_name": "gpt-4o-transcribe",
                "use_cases": ["transcription"],
                "enabled": True,
                "description": "von Hand gepflegt",
            }
        ])

        changes = seed_module.seed(collection, dry_run=False)

        document = collection.find_one({"model_id": "openai/gpt-4o-transcribe"})
        assert document is not None
        self.assertIn("live_transcription", document["use_cases"])
        self.assertIn("transcription", document["use_cases"])
        # Die vorhandene Beschreibung bleibt unangetastet.
        self.assertEqual(document["description"], "von Hand gepflegt")
        self.assertGreater(changes, 0)

    def test_dry_run_writes_nothing(self) -> None:
        collection = FakeCollection()

        changes = seed_module.seed(collection, dry_run=True)

        self.assertEqual(changes, len(seed_module.MODELS))
        self.assertEqual(collection.documents, [])


if __name__ == "__main__":
    unittest.main()
