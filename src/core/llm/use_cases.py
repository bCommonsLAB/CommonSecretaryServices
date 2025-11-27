"""
@fileoverview LLM Use Cases - Definition of supported LLM use cases

@description
Defines the use cases for LLM operations in the system.
Each use case represents a specific type of LLM operation.

@module core.llm.use_cases

@exports
- UseCase: Enum - Supported LLM use cases
"""

from enum import Enum


class UseCase(str, Enum):
    """
    Unterstützte LLM-Use-Cases.
    
    Jeder Use-Case repräsentiert einen spezifischen Typ von LLM-Operation.
    """
    # Audio/Video Transkription mit Whisper
    TRANSCRIPTION = "transcription"
    
    # Bild-zu-Text Konvertierung mit Vision API
    IMAGE2TEXT = "image2text"
    
    # PDF OCR mit Mistral OCR
    OCR_PDF = "ocr_pdf"
    
    # Text-Übersetzung und Chat-Completion
    CHAT_COMPLETION = "chat_completion"

    # Embeddings für Retrieval, RAG, Vektorspeicher
    EMBEDDING = "embedding"
    
    def __str__(self) -> str:
        """Gibt den String-Wert des Use-Cases zurück."""
        return self.value










