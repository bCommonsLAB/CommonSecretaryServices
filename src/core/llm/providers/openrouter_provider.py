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

    def _is_images_endpoint_model(self, model: str) -> bool:
        """
        Prüft, ob ein Modell voraussichtlich den Images-Endpoint unterstützt.
        
        Der Images-Endpoint ist primär für OpenAI-Modelle dokumentiert
        (z.B. DALL-E, GPT-Image). Für andere Modelle wird in der Regel
        der Chat-Endpoint mit modalities verwendet.
        """
        model_lower = model.lower().strip()
        return model_lower.startswith("openai/") or model_lower.startswith("openrouter/openai/")

    def _extract_image_bytes_from_images_response(self, response: Any) -> bytes:
        """
        Extrahiert Bild-Bytes aus der /images/generations Response.
        """
        import base64
        
        data_items = getattr(response, "data", None)
        if not data_items or len(data_items) == 0:
            raise ProcessingError("Keine Bilddaten in der OpenRouter Response gefunden")
        
        first_image = data_items[0]
        b64_json = getattr(first_image, "b64_json", None)
        image_url = getattr(first_image, "url", None)
        
        if b64_json:
            return base64.b64decode(b64_json)
        if isinstance(image_url, str) and image_url.startswith("data:image"):
            base64_data = image_url.split(",", 1)[1]
            return base64.b64decode(base64_data)
        if isinstance(image_url, str):
            # Externe URL serverseitig laden, damit der Client keine externe URL braucht
            from urllib.request import urlopen
            with urlopen(image_url) as response_stream:
                return response_stream.read()
        
        raise ProcessingError("Weder b64_json noch URL in der OpenRouter Response gefunden")

    def _extract_image_bytes_from_chat_response(self, response: ChatCompletion) -> bytes:
        """
        Extrahiert Bild-Bytes aus der chat/completions Response.
        
        OpenRouter liefert Bilder als Data-URL im Feld message.images[].image_url.url.
        """
        import base64
        
        if not response.choices or not response.choices[0].message:
            raise ProcessingError("Keine gültige Chat-Response für Bildgenerierung erhalten")
        
        message = response.choices[0].message
        images = getattr(message, "images", None)
        if not images or len(images) == 0:
            raise ProcessingError("Keine Bilder in der Chat-Response gefunden")
        
        first_image = images[0]
        
        # Unterstütze verschiedene Response-Formate (dict oder Objekt)
        image_url_obj = getattr(first_image, "image_url", None)
        if image_url_obj is None and isinstance(first_image, dict):
            image_url_obj = first_image.get("image_url")
        
        image_url = None
        if image_url_obj is not None and hasattr(image_url_obj, "url"):
            image_url = image_url_obj.url
        elif isinstance(image_url_obj, dict):
            image_url = image_url_obj.get("url")
        
        # Fallback: manchmal liegt die URL direkt im Objekt
        if image_url is None:
            image_url = getattr(first_image, "url", None)
            if image_url is None and isinstance(first_image, dict):
                image_url = first_image.get("url")
        
        if isinstance(image_url, str) and image_url.startswith("data:image"):
            base64_data = image_url.split(",", 1)[1]
            return base64.b64decode(base64_data)
        if isinstance(image_url, str):
            from urllib.request import urlopen
            with urlopen(image_url) as response_stream:
                return response_stream.read()
        
        raise ProcessingError(f"Unbekanntes Bild-URL-Format: {type(image_url)}")
    
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
    
    def text2image(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        seed: Optional[int] = None,
        **kwargs: Any
    ) -> tuple[bytes, LLMRequest]:
        """
        Generiert ein Bild aus einem Text-Prompt mit OpenRouter.
        
        OpenRouter unterstützt Bildgenerierung über den Chat-Endpoint
        (/chat/completions) mit modalities. Für OpenAI-Modelle ist
        alternativ der Images-Endpoint (/images/generations) möglich.
        
        Args:
            prompt: Text-Prompt für Bildgenerierung
            model: Zu verwendendes Modell (muss "image" in output_modalities haben)
            size: Bildgröße (z.B. "1024x1024", "1792x1024", "1024x1792")
            quality: Qualität ("standard" oder "hd")
            n: Anzahl der Bilder (default: 1, max: 1 für die meisten Modelle)
            **kwargs: Zusätzliche Parameter
            
        Returns:
            tuple[bytes, LLMRequest]: Bild-Bytes (PNG) und LLM-Request-Info
            
        Raises:
            ProcessingError: Wenn Bildgenerierung fehlschlägt
        """
        start_time = time.time()
        endpoint_used = "unknown"
        
        try:
            endpoint_used = "chat"
            response: Any = None
            
            # API-Parameter vorbereiten
            # Standard: Chat-Endpoint mit modalities (OpenRouter-Doku)
            chat_params: Dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "modalities": ["image", "text"]
            }
            
            # OpenAI-Images-Endpoint nur fuer OpenAI-Modelle verwenden
            if self._is_images_endpoint_model(model):
                endpoint_used = "images"
                images_params: Dict[str, Any] = {
                    "model": model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality
                }
                
                # Anzahl der Bilder (nur wenn > 1, da Default 1 ist)
                if n and n > 1:
                    images_params["n"] = min(n, 1)
                
                # Seed hinzufügen, falls angegeben
                seed_value = seed if seed is not None else kwargs.get("seed")
                if seed_value is not None:
                    images_params["seed"] = seed_value
                
                # Zusätzliche Parameter aus kwargs hinzufügen
                for key, value in kwargs.items():
                    if key not in ["model", "prompt", "size", "quality", "n", "seed"]:
                        images_params[key] = value
                
                response = self.client.images.generate(**images_params)
                image_bytes = self._extract_image_bytes_from_images_response(response)
            else:
                # Zusätzliche Parameter für Chat-Endpoint
                # image_config ist im OpenAI-SDK nicht immer erlaubt, daher nur whitelisted Keys
                for key, value in kwargs.items():
                    if key not in ["model", "messages", "modalities"]:
                        chat_params[key] = value
                
                response = self.client.chat.completions.create(**chat_params)
                image_bytes = self._extract_image_bytes_from_chat_response(response)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Tokens extrahieren
            usage = getattr(response, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            if tokens <= 0:
                tokens = 1
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="text2image",
                tokens=tokens,
                duration=duration,
                processor="OpenRouterProvider"
            )
            
            logger.info(
                "OpenRouter text2image",
                model=model,
                size=size,
                quality=quality,
                prompt_length=len(prompt),
                image_size_bytes=len(image_bytes),
                tokens=tokens,
                duration_ms=duration,
                endpoint=endpoint_used
            )
            
            return image_bytes, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            
            # Fehlerdetails sammeln, damit die Fehlermeldung konkret genug ist
            # fuer Debugging (Statuscode, Response-Body, Modell, Endpoint).
            error_details: Dict[str, Any] = {
                "error_type": "TEXT2IMAGE_ERROR",
                "duration_ms": duration,
                "model": model,
                # Endpoint kann im Fehlerfall unbekannt sein, daher absichern
                "endpoint": endpoint_used
            }
            
            status_code = getattr(e, "status_code", None)
            if status_code is not None:
                error_details["status_code"] = status_code
            
            response = getattr(e, "response", None)
            if response is not None:
                try:
                    error_details["response_text"] = response.text
                except Exception:
                    pass
                try:
                    error_details["response_json"] = response.json()
                except Exception:
                    pass
            
            body = getattr(e, "body", None)
            if body is not None:
                error_details["response_body"] = body
            
            raise ProcessingError(
                f"Fehler bei der OpenRouter Bildgenerierung: {str(e)}",
                details=error_details
            ) from e
    
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
            UseCase.OCR_PDF,
            UseCase.TEXT2IMAGE
        ]


