"""
@fileoverview OpenRouter Provider - OpenRouter implementation of LLMProvider protocol

@description
OpenRouter provider implementation. OpenRouter provides access to multiple
LLM providers through a unified API that is compatible with OpenAI's API.

@module core.llm.providers.openrouter_provider

@exports
- OpenRouterProvider: Class - OpenRouter provider implementation
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportGeneralTypeIssues=false
# Hinweis:
# Die OpenRouter-API nutzt OpenAI-kompatible Response-Typen, deren Stubs in der Praxis je nach Version
# von `openai` unvollständig/inkonsistent sind. Ohne diese Einstellungen erzeugt Pyright hier sehr viele
# "Unknown"-Warnungen, obwohl der Runtime-Code korrekt ist.

from typing import List, Optional, Dict, Any, cast
import time

from openai import OpenAI
from openai.types.chat import ChatCompletion

from src.utils.logger import get_logger
from ...exceptions import ProcessingError
from ...models.llm import LLMRequest
from ..use_cases import UseCase

logger = get_logger(process_id="openrouter-provider")


class OpenRouterProvider:
    """
    OpenRouter Provider-Implementierung.
    
    Implementiert das LLMProvider-Protocol für OpenRouter Services.
    OpenRouter ist kompatibel mit der OpenAI API, daher können wir den OpenAI-Client verwenden.
    Unterstützt Chat-Completion und Vision API (je nach Modell).
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialisiert den OpenRouter Provider.
        
        Args:
            api_key: OpenRouter API-Key
            base_url: Optional, benutzerdefinierte Base-URL (Standard: OpenRouter API)
            available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen aus Config
            **kwargs: Zusätzliche Parameter (werden ignoriert)
        """
        if not api_key:
            raise ValueError("OpenRouter API-Key darf nicht leer sein")
        
        # OpenRouter verwendet die OpenAI-kompatible API
        # Base-URL ist standardmäßig OpenRouter
        if base_url:
            api_base_url = base_url
        else:
            api_base_url = "https://openrouter.ai/api/v1"
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base_url,
            default_headers={
                "HTTP-Referer": kwargs.get("http_referer", "https://github.com/your-repo"),
                "X-Title": kwargs.get("app_name", "Common Secretary Services")
            }
        )
        
        self._api_key = api_key
        self._available_models = available_models or {}
    
    def get_provider_name(self) -> str:
        """Gibt den Namen des Providers zurück."""
        return "openrouter"
    
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
        OpenRouter unterstützt keine direkte Transkription.
        Transkription muss über Chat-Completion mit Audio-Modellen erfolgen.
        
        Raises:
            ProcessingError: OpenRouter unterstützt keine direkte Transkription
        """
        raise ProcessingError(
            "OpenRouter unterstützt keine direkte Audio-Transkription. "
            "Verwenden Sie einen anderen Provider für Transcription (z.B. OpenAI Whisper)."
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
            model: Zu verwendendes Modell (z.B. 'anthropic/claude-3-opus', 'openai/gpt-4')
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
            
            # response_format explizit behandeln (OpenAI-kompatibel)
            if 'response_format' in kwargs:
                response_format_value = kwargs['response_format']
                # OpenAI erwartet response_format als Dict mit {"type": "json_object"}
                # oder als String "json_object"
                if isinstance(response_format_value, dict):
                    api_params["response_format"] = response_format_value
                elif isinstance(response_format_value, str):
                    # Konvertiere String zu Dict für OpenAI-kompatible API
                    if response_format_value == "json_object":
                        api_params["response_format"] = {"type": "json_object"}
                    else:
                        api_params["response_format"] = response_format_value
            
            # Zusätzliche Parameter hinzufügen (außer response_format, das bereits behandelt wurde)
            for key, value in kwargs.items():
                if key not in ['model', 'messages', 'temperature', 'max_tokens', 'response_format']:
                    api_params[key] = value
            
            # API-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or not response.choices[0].message:
                raise ProcessingError("Keine gültige Antwort von OpenRouter erhalten")
            
            content = str(response.choices[0].message.content or "")

            # Debug-Logging (mit Guardrails):
            # - Keine API Keys/Secrets
            # - Content nur gekürzt, damit die Console nicht explodiert
            choice0 = cast(Any, response.choices[0])
            finish_reason = getattr(choice0, "finish_reason", None)
            prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
            content_chars = len(content)
            tail = content[-240:] if content_chars > 240 else content

            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

            logger.info(
                "OpenRouter chat_completion",
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                finish_reason=finish_reason,
                prompt_chars=prompt_chars,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                content_chars=content_chars,
                content_tail=tail,
            )
            
            # Tokens extrahieren
            tokens = total_tokens
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="chat_completion",
                tokens=tokens,
                duration=duration,
                processor="OpenRouterProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der OpenRouter Chat-Completion: {str(e)}",
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
        
        Args:
            image_data: Bild-Daten als Bytes
            prompt: Text-Prompt für die Bildanalyse
            model: Zu verwendendes Modell (muss Vision unterstützen)
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
                raise ProcessingError("Keine gültige Antwort von OpenRouter Vision API erhalten")
            
            content = str(response.choices[0].message.content or "")
            
            # Tokens extrahieren
            usage = getattr(response, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="vision",
                tokens=tokens,
                duration=duration,
                processor="OpenRouterProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der OpenRouter Vision API: {str(e)}",
                details={'error_type': 'VISION_ERROR', 'duration_ms': duration}
            ) from e
    
    def fetch_models_from_api(self) -> Optional[List[Dict[str, Any]]]:
        """
        Ruft die aktuell verfügbaren Modelle direkt von der OpenRouter API ab.
        
        Returns:
            Optional[List[Dict[str, Any]]]: Liste der verfügbaren Modelle oder None bei Fehler
        """
        try:
            import requests
            
            # OpenRouter Models API Endpoint
            url = "https://openrouter.ai/api/v1/models"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://github.com/your-repo",
                "X-Title": "Common Secretary Services"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'data' in data:
                    return data['data']
            return None
        except Exception:
            # Bei Fehlern None zurückgeben (z.B. wenn API nicht erreichbar ist)
            return None
    
    def get_available_models(self, use_case: UseCase) -> List[str]:
        """
        Gibt die verfügbaren Modelle für einen Use-Case zurück.
        Lädt Modelle ausschließlich aus Config (config.yaml).
        
        OpenRouter bietet Zugriff auf viele Modelle verschiedener Provider.
        Diese müssen in der Config konfiguriert werden.
        
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
        OpenRouter unterstützt keine Embeddings über dieses Interface.
        
        Raises:
            ProcessingError: OpenRouter unterstützt keine Embeddings
        """
        raise ProcessingError(
            "OpenRouter unterstützt keine Embeddings über dieses Interface. "
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


