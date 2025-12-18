"""
@fileoverview Ollama Provider - Ollama implementation of LLMProvider protocol

@description
Ollama provider implementation. Ollama is a local LLM server that provides
an OpenAI-compatible API. This provider connects to a local Ollama instance
running on the default port (11434).

@module core.llm.providers.ollama_provider

@exports
- OllamaProvider: Class - Ollama provider implementation
"""

from typing import List, Optional, Dict, Any
import time

from openai import OpenAI
from openai.types.chat import ChatCompletion

from ...exceptions import ProcessingError
from ...models.audio import TranscriptionResult, TranscriptionSegment
from ...models.llm import LLMRequest
from ..protocols import LLMProvider
from ..use_cases import UseCase


class OllamaProvider:
    """
    Ollama Provider-Implementierung.
    
    Implementiert das LLMProvider-Protocol für lokale Ollama-Services.
    Ollama bietet eine OpenAI-kompatible API, daher können wir den OpenAI-Client verwenden.
    Unterstützt Chat-Completion und Vision API (je nach Modell).
    
    Hinweis: Ollama muss lokal installiert und gestartet sein.
    Standard-URL: http://localhost:11434/v1
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialisiert den Ollama Provider.
        
        Args:
            api_key: API-Key (kann leer sein oder "ollama" als Placeholder, wird nicht verwendet)
            base_url: Optional, benutzerdefinierte Base-URL (Standard: http://localhost:11434/v1)
            available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen aus Config
            **kwargs: Zusätzliche Parameter (werden ignoriert)
        """
        # Ollama benötigt keinen echten API-Key, aber der OpenAI-Client erwartet einen
        # Wir verwenden "ollama" als Placeholder, wenn keiner angegeben wurde
        if not api_key or api_key == "not-configured":
            api_key = "ollama"
        
        # Base-URL ist standardmäßig die lokale Ollama-Instanz
        if base_url:
            api_base_url = base_url
        else:
            api_base_url = "http://localhost:11434/v1"
        
        # Erstelle OpenAI-kompatiblen Client für Ollama
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base_url
        )
        
        self._api_key = api_key
        self._available_models = available_models or {}
    
    def get_provider_name(self) -> str:
        """Gibt den Namen des Providers zurück."""
        return "ollama"
    
    def get_client(self) -> OpenAI:
        """Gibt den OpenAI-kompatiblen Client zurück."""
        return self.client
    
    def transcribe(
        self,
        audio_data: bytes | Any,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any
    ) -> tuple[Any, LLMRequest]:
        """
        Ollama unterstützt keine direkte Audio-Transkription.
        Transkription muss über Chat-Completion mit Audio-Modellen erfolgen
        (falls das Modell Audio unterstützt).
        
        Raises:
            ProcessingError: Ollama unterstützt keine direkte Transkription
        """
        raise ProcessingError(
            "Ollama unterstützt keine direkte Audio-Transkription. "
            "Verwenden Sie einen anderen Provider für Transcription (z.B. OpenAI Whisper) "
            "oder verwenden Sie Chat-Completion mit einem Audio-fähigen Modell."
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
            model: Zu verwendendes Modell (z.B. 'llama3', 'mistral', 'codellama')
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
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature
            }
            
            if max_tokens:
                api_params["max_tokens"] = max_tokens
            
            # Zusätzliche Parameter hinzufügen
            for key, value in kwargs.items():
                if key not in ['model', 'messages', 'temperature', 'max_tokens']:
                    api_params[key] = value
            
            # API-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or not response.choices[0].message:
                raise ProcessingError("Keine gültige Antwort von Ollama erhalten")
            
            content = response.choices[0].message.content or ""
            
            # Tokens extrahieren
            tokens = 0
            if response.usage:
                tokens = response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="chat_completion",
                tokens=tokens,
                duration=duration,
                processor="OllamaProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der Ollama Chat-Completion: {str(e)}",
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
        Verarbeitet ein Bild mit Vision API (wenn das Modell Vision unterstützt).
        
        Ollama unterstützt Vision-Modelle wie 'llava', 'bakllava', etc.
        
        Args:
            image_data: Bild-Daten als Bytes
            prompt: Text-Prompt für die Bildanalyse
            model: Zu verwendendes Modell (muss Vision unterstützen, z.B. 'llava')
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
            
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": kwargs.get("detail", "high")
                                }
                            }
                        ]
                    }
                ]
            }
            
            if max_tokens:
                api_params["max_tokens"] = max_tokens
            
            if "temperature" in kwargs:
                api_params["temperature"] = kwargs["temperature"]
            
            # API-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or not response.choices[0].message:
                raise ProcessingError("Keine gültige Antwort von Ollama Vision API erhalten")
            
            content = response.choices[0].message.content or ""
            
            # Tokens extrahieren
            tokens = 0
            if response.usage:
                tokens = response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="vision",
                tokens=tokens,
                duration=duration,
                processor="OllamaProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der Ollama Vision API: {str(e)}",
                details={'error_type': 'VISION_ERROR', 'duration_ms': duration}
            ) from e
    
    def get_available_models(self, use_case: UseCase) -> List[str]:
        """
        Gibt die verfügbaren Modelle für einen Use-Case zurück.
        Lädt Modelle ausschließlich aus Config (config.yaml).
        
        Ollama unterstützt viele verschiedene Modelle, die lokal installiert werden können.
        Diese müssen in der Config konfiguriert werden.
        
        Beispiele für Ollama-Modelle:
        - Chat: llama3, mistral, codellama, phi3
        - Vision: llava, bakllava
        
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
        Ollama unterstützt keine Embeddings über dieses Interface.
        
        Raises:
            ProcessingError: Ollama unterstützt keine Embeddings
        """
        raise ProcessingError(
            "Ollama unterstützt keine Embeddings über dieses Interface. "
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
            UseCase.IMAGE2TEXT,
            UseCase.OCR_PDF
        ]


