"""
@fileoverview OpenAI Provider - OpenAI implementation of LLMProvider protocol

@description
OpenAI provider implementation. Provides access to OpenAI's API including
Whisper transcription, GPT chat completion, and Vision API.

@module core.llm.providers.openai_provider

@exports
- OpenAIProvider: Class - OpenAI provider implementation
"""

from typing import List, Optional, Dict, Any
from pathlib import Path
import io
import time

from openai import OpenAI
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat import ChatCompletion

from ...exceptions import ProcessingError
from ...models.audio import TranscriptionResult, TranscriptionSegment
from ...models.llm import LLMRequest
from ..protocols import LLMProvider
from ..use_cases import UseCase


class OpenAIProvider:
    """
    OpenAI Provider-Implementierung.
    
    Implementiert das LLMProvider-Protocol für OpenAI-Services.
    Unterstützt Transcription, Chat-Completion und Vision API.
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        available_models: Optional[Dict[str, List[str]]] = None,
        **kwargs: Any
    ) -> None:
        """
        Initialisiert den OpenAI Provider.
        
        Args:
            api_key: OpenAI API-Key
            base_url: Optional, benutzerdefinierte Base-URL
            available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen aus Config
            **kwargs: Zusätzliche Parameter (werden ignoriert)
        """
        if not api_key:
            raise ValueError("OpenAI API-Key darf nicht leer sein")
        
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)
        
        self._api_key = api_key
        self._available_models = available_models or {}
    
    def get_provider_name(self) -> str:
        """Gibt den Namen des Providers zurück."""
        return "openai"
    
    def get_client(self) -> OpenAI:
        """Gibt den OpenAI-Client zurück."""
        return self.client
    
    def transcribe(
        self,
        audio_data: bytes | Path,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any
    ) -> tuple[TranscriptionResult, LLMRequest]:
        """
        Transkribiert Audio-Daten mit Whisper.
        
        Args:
            audio_data: Audio-Daten als Bytes oder Pfad zur Datei
            model: Zu verwendendes Modell (z.B. 'whisper-1')
            language: Optional, Sprache des Audios (ISO 639-1)
            **kwargs: Zusätzliche Parameter (response_format, etc.)
            
        Returns:
            tuple[TranscriptionResult, LLMRequest]: Transkriptionsergebnis und LLM-Request-Info
            
        Raises:
            ProcessingError: Bei Fehlern während der Transkription
        """
        start_time = time.time()
        
        try:
            # Bereite Datei vor
            if isinstance(audio_data, Path):
                audio_file = open(audio_data, 'rb')
                file_tuple = ("audio.mp3", audio_file, "audio/mpeg")
            else:
                audio_file = io.BytesIO(audio_data)
                file_tuple = ("audio.mp3", audio_file, "audio/mpeg")
            
            # API-Parameter vorbereiten
            api_params: Dict[str, Any] = {
                "model": model,
                "file": file_tuple,
                "response_format": kwargs.get("response_format", "verbose_json")
            }
            
            if language and language != "auto":
                api_params["language"] = language
            
            # API-Aufruf
            response: TranscriptionVerbose = self.client.audio.transcriptions.create(**api_params)
            
            # Datei schließen falls nötig
            if isinstance(audio_data, Path) and hasattr(audio_file, 'close'):
                audio_file.close()
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Tokens schätzen oder aus Response extrahieren
            tokens = 0
            if hasattr(response, 'usage') and response.usage:
                tokens = response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0
            else:
                # Schätzung basierend auf Textlänge
                text = response.text if hasattr(response, 'text') else ""
                tokens = int(len(text.split()) * 1.5)
            
            # Stelle sicher, dass tokens mindestens 1 ist (eine API-Anfrage verbraucht immer Tokens)
            if tokens <= 0:
                tokens = 1  # Mindestwert für eine API-Anfrage
            
            # TranscriptionResult erstellen
            transcription_text = response.text if hasattr(response, 'text') and response.text else "[Keine Sprache erkannt]"
            
            # Sprache konvertieren falls nötig
            detected_language = language or "auto"
            if detected_language == "auto" and hasattr(response, 'language'):
                detected_language = self._convert_to_iso_code(response.language)
            
            segment = TranscriptionSegment(
                text=transcription_text,
                segment_id=0,
                start=0.0,
                end=duration / 1000.0,
                title=None
            )
            
            transcription_result = TranscriptionResult(
                text=transcription_text,
                source_language=detected_language,
                segments=[segment]
            )
            
            # LLMRequest erstellen
            llm_request = LLMRequest(
                model=model,
                purpose="transcription",
                tokens=tokens,
                duration=duration,
                processor="OpenAIProvider"
            )
            
            return transcription_result, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der OpenAI-Transkription: {str(e)}",
                details={'error_type': 'TRANSCRIPTION_ERROR', 'duration_ms': duration}
            ) from e
    
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
            **kwargs: Zusätzliche Parameter (functions, function_call, etc.)
            
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
            
            # Zusätzliche Parameter hinzufügen (functions, function_call, etc.)
            for key, value in kwargs.items():
                if key not in ['model', 'messages', 'temperature', 'max_tokens']:
                    api_params[key] = value
            
            # API-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(**api_params)
            
            # Dauer berechnen
            duration = (time.time() - start_time) * 1000
            
            # Antwort extrahieren
            if not response.choices or not response.choices[0].message:
                raise ProcessingError("Keine gültige Antwort von OpenAI erhalten")
            
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
                processor="OpenAIProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der OpenAI Chat-Completion: {str(e)}",
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
        Verarbeitet ein Bild mit Vision API.
        
        Args:
            image_data: Bild-Daten als Bytes
            prompt: Text-Prompt für die Bildanalyse
            model: Zu verwendendes Modell (z.B. 'gpt-4o')
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
                raise ProcessingError("Keine gültige Antwort von OpenAI Vision API erhalten")
            
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
                processor="OpenAIProvider"
            )
            
            return content, llm_request
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            raise ProcessingError(
                f"Fehler bei der OpenAI Vision API: {str(e)}",
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
        OpenAI unterstützt keine direkte Embedding-API über dieses Interface.
        Verwenden Sie den OpenAI Embeddings-Endpoint direkt oder VoyageAI für Embeddings.
        
        Raises:
            ProcessingError: OpenAI unterstützt keine Embeddings über dieses Interface
        """
        raise ProcessingError(
            "OpenAI unterstützt keine Embeddings über dieses Interface. "
            "Verwenden Sie VoyageAI für Embeddings oder den OpenAI Embeddings-Endpoint direkt."
        )
    
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
        OpenAI unterstützt Text2Image über eine separate Images API.
        Diese Implementierung nutzt OpenRouter für Text2Image.
        
        Raises:
            ProcessingError: OpenAI Provider unterstützt Text2Image nicht über dieses Interface
        """
        raise ProcessingError(
            "OpenAI Provider unterstützt Text2Image nicht über dieses Interface. "
            "Verwenden Sie OpenRouter Provider für Text2Image oder die OpenAI Images API direkt."
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
            UseCase.TRANSCRIPTION,
            UseCase.IMAGE2TEXT,
            UseCase.CHAT_COMPLETION,
            UseCase.OCR_PDF
        ]
    
    def _convert_to_iso_code(self, language: str) -> str:
        """
        Konvertiert Whisper Sprachbezeichnung in ISO 639-1 Code.
        
        Args:
            language: Sprachbezeichnung von Whisper (z.B. 'english')
            
        Returns:
            str: ISO 639-1 Sprachcode (z.B. 'en')
        """
        language_map: Dict[str, str] = {
            'english': 'en',
            'german': 'de',
            'french': 'fr',
            'spanish': 'es',
            'italian': 'it',
            'portuguese': 'pt',
            'arabic': 'ar',
            'chinese': 'zh',
            'japanese': 'ja',
            'korean': 'ko',
            'russian': 'ru',
            'turkish': 'tr',
            'hindi': 'hi',
            'bengali': 'bn',
            'polish': 'pl',
            'czech': 'cs',
            'dutch': 'nl'
        }
        
        normalized = language.lower().strip()
        
        if len(normalized) == 2:
            return normalized
        
        return language_map.get(normalized, 'en')


