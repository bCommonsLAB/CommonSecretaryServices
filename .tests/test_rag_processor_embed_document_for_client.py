import asyncio
import types
from typing import Any, List

from src.core.resource_tracking import ResourceCalculator
from src.processors.rag_processor import RAGProcessor


class _FakeVoyageClient:
    """Einfacher Fake-Client für voyageai, der deterministische Embeddings zurückgibt.
    
    Dieser Client vermeidet externe API-Aufrufe in Tests. Jede Eingabezeile wird
    auf ein kleines, festes Embedding abgebildet.
    """

    def __init__(self, api_key: str) -> None:  # pragma: no cover - triviale Initialisierung
        self.api_key = api_key

    def embed(self, texts: List[str], model: str, input_type: str) -> Any:
        # Gib für jeden Text ein kleines Dummy-Embedding zurück
        return types.SimpleNamespace(
            embeddings=[[float(len(t)), 1.0] for t in texts]
        )


class _FakeVoyageModule:
    """Wrapper, um die voyageai-API-Oberfläche für Tests nachzubilden."""

    Client = _FakeVoyageClient


def test_embed_document_for_client_creates_chunks_and_embeddings(monkeypatch: Any) -> None:
    """Testet, dass embed_document_for_client Chunks + Embeddings zurückgibt ohne DB."""
    # Umgebung für RAGProcessor vorbereiten
    import src.processors.rag_processor as rag_processor

    # Fake voyageai-Modul einschleusen und API-Key setzen
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(rag_processor, "voyageai", _FakeVoyageModule, raising=False)

    # Processor initialisieren
    calculator = ResourceCalculator()
    processor = RAGProcessor(resource_calculator=calculator)

    markdown_text = "# Titel\n\nDies ist ein Test.\n\nNoch ein Absatz."

    # Async-Methode synchron ausführen
    result = asyncio.run(
        processor.embed_document_for_client(
            text=markdown_text,
            document_id=None,
            chunk_size=100,
            chunk_overlap=10,
            embedding_model=None,
            metadata={"source": "unit-test"},
        )
    )

    # Basis-Assertions zum Dokument
    assert result.document_id
    assert result.total_chunks == len(result.chunks)
    assert result.metadata.get("source") == "unit-test"
    # Das verwendete Embedding-Modell wird im Ergebnis zurückgegeben
    assert isinstance(result.embedding_model, str)
    assert result.embedding_model

    # Es sollte mindestens ein Chunk existieren, jeder mit Embedding
    assert result.chunks
    for chunk in result.chunks:
        assert chunk.text.strip()
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 2


