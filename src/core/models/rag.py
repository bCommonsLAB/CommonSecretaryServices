"""
@fileoverview RAG Models - Dataclasses for RAG processing and retrieval

@description
RAG-specific types and models. This file defines all dataclasses for RAG processing,
including embedding, chunking, retrieval, and query responses.

Main classes:
- RAGChunk: Single text chunk with embedding metadata
- RAGEmbeddingResult: Result of embedding process (chunks, document ID, etc.)
- RAGQueryResult: Single retrieval result with score
- RAGQueryResponse: Complete query response with retrieval results and LLM answer
- RAGProcessingResult: Cacheable processing result for embedding process
- RAGResponse: API response for both endpoints

Features:
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Deserialization from dictionary (from_dict)
- Integration with LLMInfo for embedding and generation tracking

@module core.models.rag

@exports
- RAGChunk: Dataclass - Text chunk with metadata
- RAGEmbeddingResult: Dataclass - Embedding process result
- RAGQueryResult: Dataclass - Single retrieval result
- RAGQueryResponse: Dataclass - Query response data
- RAGProcessingResult: Class - Cacheable processing result
- RAGResponse: Dataclass - API response for RAG endpoints

@usedIn
- src.processors.rag_processor: Uses all RAG models
- src.api.routes.rag_routes: Uses RAGResponse for API responses

@dependencies
- Internal: src.core.models.base - BaseResponse, ProcessInfo, ErrorInfo
- Internal: src.core.models.enums - ProcessingStatus
- Internal: src.core.models.protocols - CacheableResult
- Internal: src.core.exceptions - ProcessingError
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union

from .base import BaseResponse, ProcessInfo
from .enums import ProcessingStatus
from .protocols import CacheableResult


@dataclass(frozen=True)
class RAGChunk:
    """Ein einzelner Text-Chunk mit Embedding-Metadaten."""
    text: str
    chunk_index: int
    document_id: str
    embedding: Optional[List[float]] = None
    heading_context: Optional[str] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validiert die Chunk-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if self.chunk_index < 0:
            raise ValueError("Chunk-Index muss nicht-negativ sein")
        if not self.document_id.strip():
            raise ValueError("Document-ID darf nicht leer sein")
        if self.start_char is not None and self.start_char < 0:
            raise ValueError("Start-Char muss nicht-negativ sein")
        if self.end_char is not None and self.start_char is not None and self.end_char < self.start_char:
            raise ValueError("End-Char muss größer oder gleich Start-Char sein")
        if self.embedding is not None and len(self.embedding) == 0:
            raise ValueError("Embedding darf nicht leer sein wenn gesetzt")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Chunk in ein Dictionary."""
        return {
            "text": self.text,
            "chunk_index": self.chunk_index,
            "document_id": self.document_id,
            "embedding": self.embedding,
            "heading_context": self.heading_context,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGChunk':
        """Erstellt einen RAGChunk aus einem Dictionary."""
        return cls(
            text=data['text'],
            chunk_index=data['chunk_index'],
            document_id=data['document_id'],
            embedding=data.get('embedding'),
            heading_context=data.get('heading_context'),
            start_char=data.get('start_char'),
            end_char=data.get('end_char'),
            metadata=data.get('metadata', {})
        )


@dataclass(frozen=True)
class RAGEmbeddingResult:
    """Ergebnis des Embedding-Prozesses."""
    document_id: str
    chunks: List[RAGChunk]
    total_chunks: int
    embedding_dimensions: int
    embedding_model: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validiert das Embedding-Ergebnis."""
        if not self.document_id.strip():
            raise ValueError("Document-ID darf nicht leer sein")
        if len(self.chunks) == 0:
            raise ValueError("Mindestens ein Chunk erforderlich")
        if self.total_chunks != len(self.chunks):
            raise ValueError("Total-Chunks muss der Anzahl der Chunks entsprechen")
        if self.embedding_dimensions <= 0:
            raise ValueError("Embedding-Dimensionen müssen positiv sein")
        if not self.embedding_model.strip():
            raise ValueError("Embedding-Modell darf nicht leer sein")
        if not self.created_at.strip():
            raise ValueError("Created-At darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "document_id": self.document_id,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "total_chunks": self.total_chunks,
            "embedding_dimensions": self.embedding_dimensions,
            "embedding_model": self.embedding_model,
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGEmbeddingResult':
        """Erstellt ein RAGEmbeddingResult aus einem Dictionary."""
        chunks = [RAGChunk.from_dict(c) for c in data.get('chunks', [])]
        return cls(
            document_id=data['document_id'],
            chunks=chunks,
            total_chunks=data['total_chunks'],
            embedding_dimensions=data['embedding_dimensions'],
             embedding_model=data.get('embedding_model', ''),
            created_at=data['created_at'],
            metadata=data.get('metadata', {})
        )


@dataclass(frozen=True)
class RAGQueryResult:
    """Ein einzelnes Retrieval-Ergebnis mit Score."""
    chunk: RAGChunk
    score: float
    rank: int

    def __post_init__(self) -> None:
        """Validiert das Query-Ergebnis."""
        if self.score < 0.0 or self.score > 1.0:
            raise ValueError("Score muss zwischen 0.0 und 1.0 liegen")
        if self.rank < 1:
            raise ValueError("Rank muss mindestens 1 sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "chunk": self.chunk.to_dict(),
            "score": self.score,
            "rank": self.rank
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGQueryResult':
        """Erstellt ein RAGQueryResult aus einem Dictionary."""
        return cls(
            chunk=RAGChunk.from_dict(data['chunk']),
            score=data['score'],
            rank=data['rank']
        )


@dataclass(frozen=True)
class RAGQueryResponse:
    """Komplette Query-Antwort mit Retrieval-Ergebnissen und LLM-Antwort."""
    query: str
    retrieval_results: List[RAGQueryResult]
    llm_answer: Optional[str] = None
    llm_model: Optional[str] = None
    total_results: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validiert die Query-Antwort."""
        if not self.query.strip():
            raise ValueError("Query darf nicht leer sein")
        if self.total_results != len(self.retrieval_results):
            raise ValueError("Total-Results muss der Anzahl der Retrieval-Ergebnisse entsprechen")
        if len(self.retrieval_results) > 0:
            # Validiere, dass Ranks konsistent sind
            ranks = [r.rank for r in self.retrieval_results]
            if sorted(ranks) != list(range(1, len(ranks) + 1)):
                raise ValueError("Ranks müssen konsistent von 1 beginnend sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Antwort in ein Dictionary."""
        return {
            "query": self.query,
            "retrieval_results": [r.to_dict() for r in self.retrieval_results],
            "llm_answer": self.llm_answer,
            "llm_model": self.llm_model,
            "total_results": self.total_results,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGQueryResponse':
        """Erstellt ein RAGQueryResponse aus einem Dictionary."""
        retrieval_results = [RAGQueryResult.from_dict(r) for r in data.get('retrieval_results', [])]
        return cls(
            query=data['query'],
            retrieval_results=retrieval_results,
            llm_answer=data.get('llm_answer'),
            llm_model=data.get('llm_model'),
            total_results=data.get('total_results', len(retrieval_results)),
            metadata=data.get('metadata', {})
        )


class RAGProcessingResult(CacheableResult):
    """Cacheable Result für den Embedding-Prozess."""
    
    def __init__(
        self,
        embedding_result: RAGEmbeddingResult,
        process_id: str,
        status: ProcessingStatus = ProcessingStatus.SUCCESS
    ):
        """
        Initialisiert das RAG Processing Result.
        
        Args:
            embedding_result: Das Embedding-Ergebnis
            process_id: Die Prozess-ID
            status: Der Verarbeitungsstatus
        """
        self.embedding_result: RAGEmbeddingResult = embedding_result
        self.process_id: str = process_id
        self.status: ProcessingStatus = status

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "embedding_result": self.embedding_result.to_dict(),
            "process_id": self.process_id,
            "status": self.status.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGProcessingResult':
        """Erstellt ein RAGProcessingResult aus einem Dictionary."""
        embedding_result = RAGEmbeddingResult.from_dict(data['embedding_result'])
        return cls(
            embedding_result=embedding_result,
            process_id=data['process_id'],
            status=ProcessingStatus(data['status'])
        )


@dataclass(frozen=True, init=False)
class RAGResponse(BaseResponse):
    """API Response für RAG-Endpoints."""
    data: Optional[Union[RAGEmbeddingResult, RAGQueryResponse]] = field(default=None)

    def __init__(
        self,
        data: Optional[Union[RAGEmbeddingResult, RAGQueryResponse]] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die RAGResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        if self.data:
            base_dict['data'] = self.data.to_dict()
        return base_dict

