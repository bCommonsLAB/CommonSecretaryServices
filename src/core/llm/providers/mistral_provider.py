"""
@fileoverview Mistral Provider - Mistral AI implementation of LLMProvider protocol

@description
Mistral AI provider implementation. Provides access to Mistral's API for
chat completion and OCR operations.

@module core.llm.providers.mistral_provider

@exports
- MistralProvider: Class - Mistral provider implementation
"""

from typing import List, Optional, Dict, Any
import time

try:
    from mistralai import Mistral
    from mistralai.models import UserMessage, SystemMessage, AssistantMessage
    from mistralai.models import TextChunk, ImageURLChunk
except ImportError:
    Mistral = None  # type: ignore
    UserMessage = None  # type: ignore
    SystemMessage = None  # type: ignore
    AssistantMessage = None  # type: ignore
    TextChunk = None  # type: ignore
    ImageURLChunk = None  # type: ignore

from ...exceptions import ProcessingError
from ...models.llm import LLMRequest
from ..protocols import LLMProvider
from ..use_cases import UseCase


class MistralProvider:
    """
    Mistral Provider-Implementierung.
    
    Implementiert das LLMProvider-Protocol für Mistral AI Services.
    Unterstützt Chat-Completion und OCR (über Chat-Completion mit Bildern).
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialisiert den Mistral Provider.
        
        Args:
            api_key: Mistral API-Key
            base_url: Optional, benutzerdefinierte Base-URL
            available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen aus Config
            **kwargs: Zusätzliche Parameter (werden ignoriert)
        """
        if Mistral is None:
            raise ImportError(
                "mistralai Paket nicht installiert. "
                "Installieren Sie es mit: pip install mistralai"
            )
        
        if not api_key:
            raise ValueError("Mistral API-Key darf nicht leer sein")
        
        # Mistral Client initialisieren
        # base_url wird über server_url Parameter unterstützt, wenn nötig
        self.client = Mistral(api_key=api_key)
        if base_url:
            # Mistral unterstützt server_url Parameter für benutzerdefinierte URLs
            # Dies wird bei jedem API-Aufruf übergeben
            self._base_url = base_url
        else:
            self._base_url = None
        
        self._api_key = api_key
        self._available_models = available_models or {}
    
    def get_provider_name(self) -> str:
        """Gibt den Namen des Providers zurück."""
        return "mistral"
    
    def get_client(self) -> Any:
        """Gibt den Mistral-Client zurück."""
        return self.client
    
    def transcribe(
        self,
        audio_data: bytes | Any,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any
    ) -> tuple[Any, LLMRequest]:
        """
        Mistral unterstützt keine Transkription.
        
        Raises:
            ProcessingError: Mistral unterstützt keine Transkription
        """
        raise ProcessingError(
            "Mistral unterstützt keine Audio-Transkription. "
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
        Führt eine Chat-Completion-Anfrage durch.
        
        Args:
            messages: Liste von Nachrichten im Format [{"role": "user", "content": "..."}]
            model: Zu verwendendes Modell
            temperature: Temperature für die Antwort (0.0-2.0)
            max_tokens: Optional, maximale Anzahl Tokens
            **kwargs: Zusätzliche Parameter
            
        Returns:
            tuple[str, LLMRequest]: Antwort-Text und LLM-Request-Info
            
        Raises:
            ProcessingError: Bei Fehlern während der Chat-Completion
        """
        start_time = time.time()
        
        try:
            # Konvertiere Messages zu Mistral-Format
            mistral_messages: List[Any] = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if UserMessage is None or SystemMessage is None or AssistantMessage is None:
                    raise ImportError("mistralai Paket nicht installiert")
                if role == "system":
                    mistral_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    mistral_messages.append(AssistantMessage(content=content))
                else:  # user oder andere Rollen
                    mistral_messages.append(UserMessage(content=content))
            
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "model": model,
                "messages": mistral_messages,
                "temperature": temperature
            }
            
            if max_tokens:
                api_params["max_tokens"] = max_tokens
            
            # API-Aufruf
            response = self.client.chat.complete(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or len(response.choices) == 0:
                raise ProcessingError("Keine gültige Antwort von Mistral erhalten")
            
            # Antwort extrahieren und zu String konvertieren
            message_content = response.choices[0].message.content if response.choices[0].message else None
            content = str(message_content) if message_content is not None else ""
            
            # Tokens extrahieren
            tokens: int = 0
            if hasattr(response, 'usage') and response.usage:
                total_tokens = getattr(response.usage, 'total_tokens', None)
                if total_tokens is not None:
                    tokens = int(total_tokens)
                else:
                    tokens = 0
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="chat_completion",
                tokens=tokens,
                duration=duration,
                processor="MistralProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der Mistral Chat-Completion: {str(e)}",
                details={'error_type': 'CHAT_COMPLETION_ERROR', 'duration_ms': duration}
            ) from e
    
    def vision(
        self,
        image_data: bytes,
        prompt: str,
        model: str,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[str, LLMRequest]:
        """
        Verarbeitet ein Bild mit Mistral (über Chat-Completion mit Bildern).
        
        Args:
            image_data: Bild-Daten als Bytes
            prompt: Text-Prompt für die Bildanalyse
            model: Zu verwendendes Modell
            max_tokens: Optional, maximale Anzahl Tokens
            **kwargs: Zusätzliche Parameter
            
        Returns:
            tuple[str, LLMRequest]: Extrahierter Text und LLM-Request-Info
            
        Raises:
            ProcessingError: Bei Fehlern während der Vision-API-Verarbeitung
        """
        start_time = time.time()
        
        try:
            import base64
            
            # Bild zu Base64 kodieren
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # Mistral unterstützt Bilder über Chat-Completion mit ContentChunks
            # Erstelle Message mit Bild
            if UserMessage is None or TextChunk is None or ImageURLChunk is None:
                raise ImportError("mistralai Paket nicht installiert")
            
            # Erstelle ContentChunks für Mistral
            from mistralai.models import ImageURL
            image_url_obj = ImageURL(url=f"data:image/jpeg;base64,{image_base64}")
            content_parts: List[Any] = [
                TextChunk(text=prompt),
                ImageURLChunk(image_url=image_url_obj)  # type: ignore
            ]
            
            # Konvertiere zu Mistral-Format
            messages = [UserMessage(content=content_parts)]  # type: ignore
            
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "model": model,
                "messages": messages
            }
            
            if max_tokens:
                api_params["max_tokens"] = max_tokens
            
            if "temperature" in kwargs:
                api_params["temperature"] = kwargs["temperature"]
            else:
                api_params["temperature"] = 0.1
            
            # API-Aufruf
            response = self.client.chat.complete(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or len(response.choices) == 0:
                raise ProcessingError("Keine gültige Antwort von Mistral Vision API erhalten")
            
            # Antwort extrahieren und zu String konvertieren
            message_content = response.choices[0].message.content if response.choices[0].message else None
            content = str(message_content) if message_content is not None else ""
            
            # Tokens extrahieren
            tokens: int = 0
            if hasattr(response, 'usage') and response.usage:
                total_tokens = getattr(response.usage, 'total_tokens', None)
                if total_tokens is not None:
                    tokens = int(total_tokens)
                else:
                    tokens = 0
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="vision",
                tokens=tokens,
                duration=duration,
                processor="MistralProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der Mistral Vision API: {str(e)}",
                details={'error_type': 'VISION_ERROR', 'duration_ms': duration}
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
    
    def embedding(
        self,
        texts: List[str],
        model: str,
        input_type: str = "document",
        dimensions: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[List[List[float]], LLMRequest]:
        """
        Mistral unterstützt keine Embeddings.
        
        Raises:
            ProcessingError: Mistral unterstützt keine Embeddings
        """
        raise ProcessingError(
            "Mistral unterstützt keine Embeddings. "
            "Verwenden Sie VoyageAI für Embeddings."
        )
    
    def is_use_case_supported(self, use_case: UseCase) -> bool:
        """
        Prüft, ob der Provider einen bestimmten Use-Case unterstützt.
        
        Args:
            use_case: Der zu prüfende Use-Case
            
        Returns:
            bool: True wenn unterstützt, False sonst
        """
        return use_case in [
            UseCase.CHAT_COMPLETION,
            UseCase.OCR_PDF,
            UseCase.IMAGE2TEXT
        ]


