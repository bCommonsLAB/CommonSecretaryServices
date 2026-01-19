"""
@fileoverview LLM Provider Protocol - Interface definition for LLM providers

@description
Protocol definition for LLM providers. All provider implementations must
conform to this protocol to ensure consistent behavior across different providers.

@module core.llm.protocols

@exports
- LLMProvider: Protocol - Interface for LLM provider implementations
"""

from typing import Protocol, Any, List, Optional, Dict
from pathlib import Path

from ..models.audio import TranscriptionResult
from ..models.llm import LLMRequest
from .use_cases import UseCase


class LLMProvider(Protocol):
    """
    Protocol für LLM-Provider-Implementierungen.
    
    Alle Provider müssen dieses Protocol implementieren, um eine konsistente
    Schnittstelle für verschiedene LLM-Services zu gewährleisten.
    """
    
    def get_provider_name(self) -> str:
        """
        Gibt den Namen des Providers zurück.
        
        Returns:
            str: Name des Providers (z.B. 'openai', 'mistral', 'openrouter')
        """
        ...
    
    def get_client(self) -> Any:
        """
        Gibt den Client für den Provider zurück.
        
        Returns:
            Any: Provider-spezifischer Client (z.B. OpenAI, MistralClient)
        """
        ...
    
    def transcribe(
        self,
        audio_data: bytes | Path,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any
    ) -> tuple[TranscriptionResult, LLMRequest]:
        """
        Transkribiert Audio-Daten mit dem angegebenen Modell.
        
        Args:
            audio_data: Audio-Daten als Bytes oder Pfad zur Datei
            model: Zu verwendendes Modell (z.B. 'whisper-1')
            language: Optional, Sprache des Audios (ISO 639-1)
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            tuple[TranscriptionResult, LLMRequest]: Transkriptionsergebnis und LLM-Request-Info
            
        Raises:
            ValueError: Wenn der Provider Transkription nicht unterstützt
        """
        ...
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[str, LLMRequest]:
        """
        Führt eine Chat-Completion-Anfrage durch.
        
        Args:
            messages: Liste von Nachrichten im Format [{"role": "user", "content": "..."}]
            model: Zu verwendendes Modell
            temperature: Temperature für die Antwort (0.0-2.0)
            max_tokens: Optional, maximale Anzahl Tokens
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            tuple[str, LLMRequest]: Antwort-Text und LLM-Request-Info
            
        Raises:
            ValueError: Wenn der Provider Chat-Completion nicht unterstützt
        """
        ...
    
    def vision(
        self,
        image_data: bytes,
        prompt: str,
        model: str,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[str, LLMRequest]:
        """
        Verarbeitet ein Bild mit Vision API.
        
        Args:
            image_data: Bild-Daten als Bytes
            prompt: Text-Prompt für die Bildanalyse
            model: Zu verwendendes Modell (z.B. 'gpt-4o')
            max_tokens: Optional, maximale Anzahl Tokens
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            tuple[str, LLMRequest]: Extrahierter Text und LLM-Request-Info
            
        Raises:
            ValueError: Wenn der Provider Vision API nicht unterstützt
        """
        ...
    
    def get_available_models(self, use_case: UseCase) -> List[str]:
        """
        Gibt die verfügbaren Modelle für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case für den Modelle abgerufen werden sollen
            
        Returns:
            List[str]: Liste der verfügbaren Modell-Namen
        """
        ...
    
    def embedding(
        self,
        texts: List[str],
        model: str,
        input_type: str = "document",
        dimensions: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[List[List[float]], LLMRequest]:
        """
        Generiert Embeddings für eine Liste von Texten.
        
        Args:
            texts: Liste von Texten, für die Embeddings generiert werden sollen
            model: Zu verwendendes Embedding-Modell
            input_type: Typ der Eingabe ('document' oder 'query')
            dimensions: Optional, Anzahl der Embedding-Dimensionen
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            tuple[List[List[float]], LLMRequest]: Liste der Embeddings und LLM-Request-Info
            
        Raises:
            ValueError: Wenn der Provider Embeddings nicht unterstützt
        """
        ...
    
    def text2image(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        **kwargs: Any
    ) -> tuple[bytes, LLMRequest]:
        """
        Generiert ein Bild aus einem Text-Prompt.
        
        Args:
            prompt: Text-Prompt für Bildgenerierung
            model: Zu verwendendes Modell (muss "image" in output_modalities haben)
            size: Bildgröße (z.B. "1024x1024", "1792x1024", "1024x1792")
            quality: Qualität ("standard" oder "hd")
            n: Anzahl der Bilder (default: 1)
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            tuple[bytes, LLMRequest]: Bild-Bytes (PNG) und LLM-Request-Info
            
        Raises:
            ProcessingError: Wenn Bildgenerierung fehlschlägt oder Provider nicht unterstützt
        """
        ...
    
    def is_use_case_supported(self, use_case: UseCase) -> bool:
        """
        Prüft, ob der Provider einen bestimmten Use-Case unterstützt.
        
        Args:
            use_case: Der zu prüfende Use-Case
            
        Returns:
            bool: True wenn unterstützt, False sonst
        """
        ...


