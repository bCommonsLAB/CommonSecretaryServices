"""
@fileoverview VoyageAI Provider - VoyageAI implementation of LLMProvider protocol

@description
VoyageAI provider implementation. Provides access to VoyageAI's embedding API
for generating text embeddings.

@module core.llm.providers.voyageai_provider

@exports
- VoyageAIProvider: Class - VoyageAI provider implementation
"""

from typing import List, Optional, Dict, Any
import time

try:
    import voyageai
except ImportError:
    voyageai = None  # type: ignore

from ...exceptions import ProcessingError
from ...models.llm import LLMRequest
from ..protocols import LLMProvider
from ..use_cases import UseCase


class VoyageAIProvider:
    """
    VoyageAI Provider-Implementierung.
    
    Implementiert das LLMProvider-Protocol für VoyageAI Embedding Services.
    Unterstützt ausschließlich Embeddings (keine Chat-Completion, Vision oder Transcription).
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialisiert den VoyageAI Provider.
        
        Args:
            api_key: VoyageAI API-Key
            base_url: Optional, benutzerdefinierte Base-URL (wird von VoyageAI nicht unterstützt)
            available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen aus Config
            **kwargs: Zusätzliche Parameter (werden ignoriert)
        """
        if voyageai is None:
            raise ImportError(
                "voyageai Paket nicht installiert. "
                "Installieren Sie es mit: pip install voyageai"
            )
        
        if not api_key:
            raise ValueError("VoyageAI API-Key darf nicht leer sein")
        
        # VoyageAI Client initialisieren
        self.client = voyageai.Client(api_key=api_key)
        
        self._api_key = api_key
        self._available_models = available_models or {}
    
    def get_provider_name(self) -> str:
        """Gibt den Namen des Providers zurück."""
        return "voyageai"
    
    def get_client(self) -> Any:
        """Gibt den VoyageAI-Client zurück."""
        return self.client
    
    def transcribe(
        self,
        audio_data: bytes | Any,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any
    ) -> tuple[Any, LLMRequest]:
        """
        VoyageAI unterstützt keine Transkription.
        
        Raises:
            ProcessingError: VoyageAI unterstützt keine Transkription
        """
        raise ProcessingError(
            "VoyageAI unterstützt keine Audio-Transkription. "
            "Verwenden Sie einen anderen Provider für Transcription."
        )
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[str, LLMRequest]:
        """
        VoyageAI unterstützt keine Chat-Completion.
        
        Raises:
            ProcessingError: VoyageAI unterstützt keine Chat-Completion
        """
        raise ProcessingError(
            "VoyageAI unterstützt keine Chat-Completion. "
            "Verwenden Sie einen anderen Provider für Chat-Completion."
        )
    
    def vision(
        self,
        image_data: bytes,
        prompt: str,
        model: str,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[str, LLMRequest]:
        """
        VoyageAI unterstützt keine Vision API.
        
        Raises:
            ProcessingError: VoyageAI unterstützt keine Vision API
        """
        raise ProcessingError(
            "VoyageAI unterstützt keine Vision API. "
            "Verwenden Sie einen anderen Provider für Vision."
        )
    
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
            model: Zu verwendendes Embedding-Modell (z.B. 'voyage-3-large')
            input_type: Typ der Eingabe ('document' oder 'query')
            dimensions: Optional, Anzahl der Embedding-Dimensionen (256, 512, 1024, 2048)
            **kwargs: Zusätzliche Parameter (werden ignoriert)
            
        Returns:
            tuple[List[List[float]], LLMRequest]: Liste der Embeddings und LLM-Request-Info
            
        Raises:
            ProcessingError: Bei Fehlern während der Embedding-Generierung
        """
        start_time = time.time()
        
        try:
            if not texts:
                return [], LLMRequest(
                    model=model,
                    purpose="embedding",
                    tokens=0,
                    duration=(time.time() - start_time) * 1000,
                    processor="VoyageAIProvider"
                )
            
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "texts": texts,
                "model": model,
                "input_type": input_type
            }
            
            # Dimensionen hinzufügen, falls angegeben
            if dimensions is not None:
                api_params["output_dimension"] = dimensions
            
            # API-Aufruf
            response = self.client.embed(**api_params)  # type: ignore
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Embeddings extrahieren
            embeddings: List[List[float]] = []
            if hasattr(response, 'embeddings'):
                embeddings = response.embeddings  # type: ignore
            
            # Tokens schätzen (VoyageAI gibt keine Token-Information zurück)
            # Verwende eine konservative Schätzung: ~2.2 Zeichen pro Token
            total_chars = sum(len(text) for text in texts)
            tokens = int(total_chars / 2.2)
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="embedding",
                tokens=tokens,
                duration=duration,
                processor="VoyageAIProvider"
            )
            
            return embeddings, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der VoyageAI Embedding-Generierung: {str(e)}",
                details={'error_type': 'EMBEDDING_ERROR', 'duration_ms': duration}
            ) from e
    
    def get_available_models(self, use_case: UseCase) -> List[str]:
        """
        Gibt die verfügbaren Modelle für einen Use-Case zurück.
        Lädt Modelle ausschließlich aus Config (config.yaml).
        
        Args:
            use_case: Der Use-Case für den Modelle abgerufen werden sollen
            
        Returns:
            List[str]: Liste der verfügbaren Modell-Namen
            
        Raises:
            ProcessingError: Wenn keine Modelle in der Config für diesen Use-Case konfiguriert sind
        """
        use_case_str = use_case.value
        
        # Lade ausschließlich aus Config
        if self._available_models and use_case_str in self._available_models:
            models = self._available_models[use_case_str]
            if models:
                return models
        
        # Wenn keine Modelle in Config gefunden wurden, Fehler werfen
        raise ProcessingError(
            f"Keine Modelle für Use-Case '{use_case_str}' in der Config konfiguriert. "
            f"Bitte konfigurieren Sie 'available_models.{use_case_str}' für Provider '{self.get_provider_name()}' in config.yaml"
        )
    
    def is_use_case_supported(self, use_case: UseCase) -> bool:
        """
        Prüft, ob der Provider einen bestimmten Use-Case unterstützt.
        
        Args:
            use_case: Der zu prüfende Use-Case
            
        Returns:
            bool: True wenn unterstützt, False sonst
        """
        return use_case == UseCase.EMBEDDING



