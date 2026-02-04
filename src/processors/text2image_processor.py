"""
@fileoverview Text2Image Processor - Processing of text-to-image generation

@description
Text2Image Processor for generating images from text prompts. This processor
generates images using configured LLM providers (e.g., OpenRouter with DALL-E models).

Main operations:
- Text prompt validation
- Image generation via LLM provider
- Base64 encoding of generated images
- LLM usage tracking
- Optional caching of results

Features:
- Support for various image sizes and quality settings
- LLM tracking integration
- Caching support
- Error handling and validation

@module processors.text2image_processor

@exports
- Text2ImageProcessor: Class - Text-to-image processing processor

@usedIn
- src.api.routes.text2image_routes: API endpoint for text-to-image generation

@dependencies
- Internal: src.processors.cacheable_processor - CacheableProcessor base class
- Internal: src.core.llm - LLMConfigManager, UseCase
- Internal: src.core.models.text2image - Text2ImageResponse, Text2ImageData
- Internal: src.core.config - Configuration
"""
import hashlib
import base64
import time
import random
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.core.models.text2image import Text2ImageResponse, Text2ImageData, Text2ImageItem
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.base import ProcessInfo, ErrorInfo
from src.core.models.enums import ProcessingStatus
from src.processors.cacheable_processor import CacheableProcessor
from src.core.config import Config
from src.core.llm import LLMConfigManager, UseCase
from src.core.llm.protocols import LLMProvider


class Text2ImageProcessingResult:
    """
    Cache-fähiges Ergebnis für Text2Image-Verarbeitung.
    
    Wird für MongoDB-Caching verwendet.
    """
    def __init__(self, response: Text2ImageResponse) -> None:
        self.response = response
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return self.response.status


class Text2ImageProcessor(CacheableProcessor[Text2ImageProcessingResult]):
    """
    Text2Image Processor für die Generierung von Bildern aus Text-Prompts.
    
    Diese Klasse generiert Bilder aus Text-Prompts unter Verwendung von
    konfigurierten LLM-Providern (z.B. OpenRouter mit DALL-E Modellen).
    
    Attributes:
        default_size (str): Standard-Bildgröße (Default: "1024x1024")
        default_quality (str): Standard-Qualität (Default: "standard")
        max_prompt_length (int): Maximale Prompt-Länge in Zeichen
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "text2image_cache"
    
    # Typ-Annotationen für Instanzvariablen
    provider: Optional[LLMProvider]
    model_name: str
    
    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None,
        parent_process_info: Optional[ProcessInfo] = None
    ):
        """
        Initialisiert den Text2ImageProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        init_start = time.time()
        
        # Superklasse-Initialisierung
        super().__init__(
            resource_calculator=resource_calculator,
            process_id=process_id,
            parent_process_info=parent_process_info
        )
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            text2image_config = processor_config.get('text2image', {})
            
            # Text2Image-spezifische Konfiguration
            self.default_size = text2image_config.get('default_size', '1024x1024')
            self.default_quality = text2image_config.get('default_quality', 'standard')
            self.max_prompt_length = text2image_config.get('max_prompt_length', 1000)
            # Maximal erlaubte Anzahl Bilder fuer Preview-Workflows
            self.max_images = int(text2image_config.get('max_images', 4))
            # Maximal parallele Requests fuer Mehrfachgenerierung
            self.max_parallel_images = int(text2image_config.get('max_parallel_images', 2))
            
            # LLM Provider-Konfiguration laden
            self.llm_config_manager = LLMConfigManager()
            
            # Modell aus LLM-Config laden
            configured_model = self.llm_config_manager.get_model_for_use_case(UseCase.TEXT2IMAGE)
            if not configured_model:
                raise ProcessingError(
                    "Kein Modell für Text2Image in der LLM-Config konfiguriert. "
                    "Bitte konfigurieren Sie 'llm_config.use_cases.text2image.model' in config.yaml"
                )
            self.model_name = configured_model
            
            # Provider für Text2Image laden
            self.provider = self.llm_config_manager.get_provider_for_use_case(UseCase.TEXT2IMAGE)
            if not self.provider:
                raise ProcessingError(
                    "Kein Provider für Text2Image in der LLM-Config konfiguriert. "
                    "Bitte konfigurieren Sie 'llm_config.use_cases.text2image.provider' in config.yaml"
                )
            
            # Prüfe ob Provider Text2Image unterstützt
            if not self.provider.is_use_case_supported(UseCase.TEXT2IMAGE):
                raise ProcessingError(
                    f"Provider '{self.provider.get_provider_name()}' unterstützt Text2Image nicht. "
                    "Bitte verwenden Sie einen anderen Provider (z.B. openrouter)."
                )
            
            init_end = time.time()
            self.logger.debug(
                "Text2Image Processor initialisiert",
                model=self.model_name,
                provider=self.provider.get_provider_name(),
                default_size=self.default_size,
                default_quality=self.default_quality,
                init_time_ms=round((init_end - init_start) * 1000, 2)
            )
            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des Text2ImageProcessors", error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")
    
    def _create_cache_key(
        self,
        prompt: str,
        size: str,
        quality: str,
        model_name: str,
        n: int = 1,
        seeds: Optional[List[int]] = None
    ) -> str:
        """
        Erstellt einen Cache-Key für die Bildgenerierung.
        
        Args:
            prompt: Text-Prompt
            size: Bildgröße
            quality: Qualität
            model: Modell-Name
            n: Anzahl der Bilder
            
        Returns:
            str: Cache-Key
        """
        # Normalisiere Prompt (lowercase, strip whitespace)
        normalized_prompt = prompt.lower().strip()
        
        # Erstelle Hash aus allen Parametern
        seeds_part = ",".join(str(s) for s in (seeds or []))
        key_string = f"{normalized_prompt}|{size}|{quality}|{model_name}|{n}|{seeds_part}"
        key_hash = hashlib.sha256(key_string.encode('utf-8')).hexdigest()
        
        return f"text2image:{key_hash}"
    
    def _normalize_seeds(
        self,
        n: int,
        seed: Optional[int],
        seeds: Optional[List[int]]
    ) -> List[int]:
        """
        Normalisiert Seeds fuer Mehrfachgenerierung.
        
        - Wenn seeds uebergeben wurden, muessen sie exakt n Elemente haben.
        - Wenn seed gesetzt ist, erzeugen wir eine deterministische Sequenz.
        - Wenn nichts gesetzt ist, generieren wir zufaellige Seeds.
        """
        if seeds is not None:
            if len(seeds) != n:
                raise ProcessingError("seeds muss genau n Werte enthalten")
            for s in seeds:
                if s < 0:
                    raise ProcessingError("seeds darf keine negativen Werte enthalten")
            return seeds
        
        if seed is not None:
            if seed < 0:
                raise ProcessingError("seed darf nicht negativ sein")
            # Deterministisch: seed, seed+1, seed+2, ...
            return [seed + i for i in range(n)]
        
        # Fallback: zufaellige Seeds, damit der Client spaeter reproduzieren kann
        return [random.randint(0, 2**31 - 1) for _ in range(n)]

    async def _generate_single_image(
        self,
        prompt: str,
        size: str,
        quality: str,
        seed: int
    ) -> tuple[Text2ImageItem, LLMRequest, int]:
        """
        Generiert ein einzelnes Bild in einem Thread, damit wir parallelisieren koennen.
        """
        if not self.provider:
            raise ProcessingError("Provider für Text2Image nicht verfügbar")
        
        # Blocking Call in einen Thread auslagern
        image_bytes, llm_request = await asyncio.to_thread(
            self.provider.text2image,
            prompt=prompt,
            model=self.model_name,
            size=size,
            quality=quality,
            n=1,
            seed=seed
        )
        
        image_byte_length = len(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        image_format = "png"
        
        image_item = Text2ImageItem(
            image_base64=image_base64,
            image_format=image_format,
            size=size,
            seed=seed
        )
        
        return image_item, llm_request, image_byte_length
    
    def _save_debug_log(
        self,
        prompt: str,
        size: str,
        quality: str,
        model: str,
        seeds: List[int],
        duration_ms: float,
        image_count: int,
        total_image_bytes: int,
        total_tokens: int
    ) -> None:
        """
        Speichert Debug-Log für Text2Image-Generierung.
        
        Speichert detaillierte Informationen über die LLM-Interaktion als JSON-Datei
        für Debugging- und Analysezwecke. Analog zum Debug-Logging in WhisperTranscriber.
        
        Args:
            prompt: Der verwendete Text-Prompt
            size: Bildgröße (z.B. "1024x1024")
            quality: Qualitätseinstellung ("standard" oder "hd")
            model: Name des verwendeten Modells
            seeds: Liste der verwendeten Seeds für Reproduzierbarkeit
            duration_ms: Gesamtdauer der Generierung in Millisekunden
            image_count: Anzahl der generierten Bilder
            total_image_bytes: Gesamtgröße aller generierten Bilder in Bytes
            total_tokens: Verbrauchte Tokens (falls vom Provider gemeldet)
        """
        try:
            # Debug-Verzeichnis erstellen (analog zu WhisperTranscriber)
            debug_dir: Path = self.temp_dir / "debug" / "llm"
            debug_dir.mkdir(parents=True, exist_ok=True)
            
            # Eindeutigen Dateinamen erstellen
            timestamp: str = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename: str = f"{timestamp}_text2image.json"
            
            # Interaktionsdaten vorbereiten
            interaction_data: Dict[str, Any] = {
                'timestamp': datetime.now().isoformat(),
                'purpose': 'text2image',
                'prompt': prompt,
                'parameters': {
                    'size': size,
                    'quality': quality,
                    'image_count': image_count,
                    'seeds': seeds
                },
                'model': model,
                'provider': self.provider.get_provider_name() if self.provider else None,
                'response': {
                    'total_image_bytes': total_image_bytes,
                    'total_tokens': total_tokens,
                    'duration_ms': round(duration_ms, 2)
                }
            }
            
            # Interaktionsdaten speichern
            file_path: Path = debug_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(interaction_data, f, indent=2, ensure_ascii=False)
                
            self.logger.debug(
                "Debug-Log gespeichert",
                file_path=str(file_path),
                prompt_length=len(prompt)
            )
            
        except Exception as e:
            # Debug-Logging sollte niemals die Hauptverarbeitung unterbrechen
            self.logger.warning(
                "Fehler beim Speichern des Debug-Logs",
                error=str(e)
            )
    
    def serialize_for_cache(self, result: Text2ImageProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das Text2ImageProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das Text2ImageProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Serialisiere die Response zu einem Dictionary
        response_dict = result.response.to_dict()
        
        # Entferne LLM-Info aus ProcessInfo für Cache (wird bei Deserialisierung neu erstellt)
        if 'process' in response_dict and response_dict['process']:
            process_dict = response_dict['process'].copy()
            if 'llm_info' in process_dict:
                del process_dict['llm_info']
            response_dict['process'] = process_dict
        
        return {
            "response": response_dict,
            "cached_at": datetime.now().isoformat()
        }
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> Text2ImageProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein Text2ImageProcessingResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            Text2ImageProcessingResult: Das deserialisierte Ergebnis
        """
        # Extrahiere Response-Daten
        response_data = cached_data.get("response", {})
        
        # Erstelle Text2ImageResponse aus Dictionary
        response = Text2ImageResponse.from_dict(response_data)
        
        # Erstelle Text2ImageProcessingResult
        return Text2ImageProcessingResult(response)
    
    async def process(
        self,
        prompt: str,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        n: int = 1,
        use_cache: bool = True,
        seed: Optional[int] = None,
        seeds: Optional[List[int]] = None
    ) -> Text2ImageResponse:
        """
        Generiert ein Bild aus einem Text-Prompt.
        
        Args:
            prompt: Text-Prompt für Bildgenerierung
            size: Optional, Bildgröße (z.B. "1024x1024", "1792x1024", "1024x1792")
            quality: Optional, Qualität ("standard" oder "hd")
            n: Anzahl der Bilder (default: 1)
            use_cache: Ob Cache verwendet werden soll (default: True)
            seed: Optional, Seed für Reproduzierbarkeit
            seeds: Optional, Liste von Seeds (muss n Werte haben)
            
        Returns:
            Text2ImageResponse: Response mit generiertem Bild
            
        Raises:
            ProcessingError: Wenn die Generierung fehlschlägt
        """
        start_time = time.time()
        
        try:
            # Validierung
            if not prompt or not prompt.strip():
                raise ProcessingError("Prompt darf nicht leer sein")
            
            if len(prompt) > self.max_prompt_length:
                raise ProcessingError(
                    f"Prompt zu lang: {len(prompt)} Zeichen (max: {self.max_prompt_length})"
                )
            
            # Standardwerte setzen
            final_size = size or self.default_size
            final_quality = quality or self.default_quality
            
            # Validiere Size-Format
            if not final_size or "x" not in final_size:
                raise ProcessingError(f"Ungültiges Size-Format: {final_size}. Erwartet: 'WIDTHxHEIGHT'")
            
            try:
                width, height = final_size.split("x")
                int(width)
                int(height)
            except ValueError:
                raise ProcessingError(f"Ungültiges Size-Format: {final_size}. Erwartet: 'WIDTHxHEIGHT'")
            
            # Validiere Quality
            if final_quality not in ["standard", "hd"]:
                raise ProcessingError(f"Ungültige Quality: {final_quality}. Erlaubt: 'standard', 'hd'")
            
            # Validiere n
            final_n = n
            if final_n < 1:
                final_n = 1
            if final_n > self.max_images:
                self.logger.warning(
                    "n wurde reduziert",
                    requested_n=final_n,
                    max_images=self.max_images
                )
                final_n = self.max_images
            
            # Seeds normalisieren, damit jedes Bild einen Seed hat
            normalized_seeds = self._normalize_seeds(final_n, seed, seeds)
            
            # Cache-Key erstellen
            cache_key = self._create_cache_key(
                prompt,
                final_size,
                final_quality,
                self.model_name,
                final_n,
                normalized_seeds
            )
            
            # Cache prüfen
            if use_cache:
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    self.logger.info("Ergebnis aus Cache geladen", cache_key=cache_key)
                    response = cached_result.response  # type: ignore
                    # Aktualisiere ProcessInfo für Cache-Hinweis
                    if response.process:
                        object.__setattr__(response.process, 'is_from_cache', True)  # type: ignore
                        object.__setattr__(response.process, 'cache_key', cache_key)  # type: ignore
                    return response
            
            # Bildgenerierung via Provider
            if not self.provider:
                raise ProcessingError("Provider für Text2Image nicht verfügbar")
            
            self.logger.info(
                "Starte Bildgenerierung",
                prompt_length=len(prompt),
                size=final_size,
                quality=final_quality,
                model=self.model_name
            )
            
            image_items: List[Text2ImageItem] = []
            image_byte_lengths: List[int] = []
            llm_requests: List[LLMRequest] = []
            
            # Parallele Generierung mit Begrenzung
            semaphore = asyncio.Semaphore(self.max_parallel_images)
            
            async def _run_seed(image_seed: int) -> tuple[Text2ImageItem, LLMRequest, int]:
                async with semaphore:
                    return await self._generate_single_image(
                        prompt=prompt,
                        size=final_size,
                        quality=final_quality,
                        seed=image_seed
                    )
            
            tasks = [asyncio.create_task(_run_seed(s)) for s in normalized_seeds]
            results = await asyncio.gather(*tasks)
            
            for image_item, llm_request, image_byte_length in results:
                image_items.append(image_item)
                llm_requests.append(llm_request)
                image_byte_lengths.append(image_byte_length)
            
            # Erstelle Text2ImageData (erster Eintrag als Hauptbild)
            first_image = image_items[0]
            image_data = Text2ImageData(
                image_base64=first_image.image_base64,
                image_format=first_image.image_format,
                size=final_size,
                model=self.model_name,
                prompt=prompt,
                seed=first_image.seed,
                images=image_items if len(image_items) > 1 else None
            )
            
            # Aktualisiere ProcessInfo mit LLM-Tracking
            duration = (time.time() - start_time) * 1000
            
            if self.process_info:
                # Aktualisiere LLM-Info
                if self.process_info.llm_info:
                    new_llm_info = self.process_info.llm_info.add_request(llm_requests)
                    object.__setattr__(self.process_info, 'llm_info', new_llm_info)  # type: ignore
                else:
                    object.__setattr__(
                        self.process_info,
                        'llm_info',
                        LLMInfo(requests=llm_requests)
                    )  # type: ignore
                
                # Setze completed und duration
                object.__setattr__(self.process_info, 'completed', datetime.now().isoformat())  # type: ignore
                object.__setattr__(self.process_info, 'duration', duration)  # type: ignore
            
            # Erstelle RequestInfo
            from src.core.models.base import RequestInfo
            request_info = RequestInfo(
                processor="text2image",
                timestamp=datetime.now().isoformat(),
                parameters={
                    "prompt": prompt,
                    "size": final_size,
                    "quality": final_quality,
                    "n": final_n,
                    "seed": seed,
                    "seeds": normalized_seeds,
                    "use_cache": use_cache
                }
            )
            
            # Erstelle Response
            response = Text2ImageResponse(
                request=request_info,
                process=self.process_info,
                status=ProcessingStatus.SUCCESS,
                data=image_data
            )
            
            # Cache speichern
            if use_cache:
                result = Text2ImageProcessingResult(response)
                self.save_to_cache(cache_key, result)
                self.logger.info("Ergebnis im Cache gespeichert", cache_key=cache_key)
            
            self.logger.info(
                "Bildgenerierung erfolgreich",
                prompt_length=len(prompt),
                image_count=len(image_items),
                image_size_bytes=image_byte_lengths[0] if image_byte_lengths else 0,
                duration_ms=duration,
                tokens=sum(r.tokens for r in llm_requests)
            )
            
            # Debug-Log speichern (analog zu WhisperTranscriber)
            self._save_debug_log(
                prompt=prompt,
                size=final_size,
                quality=final_quality,
                model=self.model_name,
                seeds=normalized_seeds,
                duration_ms=duration,
                image_count=len(image_items),
                total_image_bytes=sum(image_byte_lengths),
                total_tokens=sum(r.tokens for r in llm_requests)
            )
            
            return response
            
        except ProcessingError:
            raise
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            self.logger.error("Fehler bei der Bildgenerierung", error=e, duration_ms=duration)
            
            error_info = ErrorInfo(
                code="TEXT2IMAGE_ERROR",
                message=str(e),
                details={"duration_ms": duration}
            )
            
            # Erstelle RequestInfo für Error-Response
            from src.core.models.base import RequestInfo
            request_info = RequestInfo(
                processor="text2image",
                timestamp=datetime.now().isoformat(),
                parameters={}
            )
            
            response = Text2ImageResponse(
                request=request_info,
                process=self.process_info,
                status=ProcessingStatus.ERROR,
                error=error_info
            )
            
            return response
