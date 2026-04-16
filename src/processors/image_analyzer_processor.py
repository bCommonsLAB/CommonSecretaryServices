"""
@fileoverview Image Analyzer Processor - Template-basierte Bildanalyse mit Vision API

@description
Prozessor für die Analyse und Klassifizierung von Bildern anhand von Templates.
Kombiniert Vision-API (Bilderkennung) mit der shared Template-Engine aus
template_utils für strukturierte Feature-Extraktion.

Unterschied zu ImageOCR:
- ImageOCR liest TEXT aus Bildern (OCR)
- ImageAnalyzer extrahiert MERKMALE und KLASSIFIZIERUNGEN aus Bildern

Wiederverwendete Komponenten:
- template_utils: Template-Laden, -Parsen, -Füllen (shared mit WhisperTranscriber)
- Image2TextService: Bild-Preprocessing (convert_image_file_to_bytes)
- LLMConfigManager: Provider/Modell-Konfiguration
- CacheableProcessor: MongoDB-Caching

@module processors.image_analyzer_processor

@exports
- ImageAnalyzerProcessor: Class - Prozessor für template-basierte Bildanalyse

@usedIn
- src.api.routes.image_analyzer_routes: API-Endpoint für Bildanalyse

@dependencies
- Internal: src.utils.template_utils - Shared Template-Engine
- Internal: src.utils.image2text_utils - Bild-Preprocessing
- Internal: src.core.llm - LLM Provider und UseCase Konfiguration
- Internal: src.processors.cacheable_processor - CacheableProcessor
- Internal: src.core.models.transformer - TransformationResult, TransformerData
"""

import hashlib
import json
import time
import requests
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse

from PIL import Image

from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.core.llm import LLMConfigManager, UseCase
from src.core.llm.protocols import LLMProvider
from src.core.models.base import ErrorInfo
from src.core.models.enums import OutputFormat
from src.core.models.transformer import (
    TransformationResult,
    TransformerData,
    TransformerResponse,
)
from src.core.resource_tracking import ResourceCalculator
from src.processors.cacheable_processor import CacheableProcessor
from src.utils import template_utils


class ImageAnalyzerProcessor(CacheableProcessor[TransformationResult]):
    """
    Prozessor für template-basierte Bildanalyse.
    
    Nimmt ein Bild und ein Template entgegen, sendet beides an die Vision-API
    und liefert strukturierte Daten zurück – analog zum Transformer-Template-
    Endpoint, aber mit Bildern statt Text.
    """

    cache_collection_name = "image_analyzer_cache"

    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None
    ):
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)

        config = Config()
        processor_config = config.get('processors.imageanalyzer', {})
        self.max_file_size: int = processor_config.get('max_file_size', 10 * 1024 * 1024)
        self.max_resolution: int = processor_config.get('max_resolution', 4096)

        # Bild-Preprocessing-Einstellungen (gleiche wie Image2TextService)
        openai_config = config.get('processors', {}).get('openai', {})
        self.max_image_size: int = openai_config.get('max_image_size', 2048)
        self.image_quality: int = openai_config.get('image_quality', 85)

        self.llm_config_manager = LLMConfigManager()

    # --- Bild-Hilfsfunktionen (wiederverwendet aus Image2TextService-Logik) ---

    def _convert_image_to_bytes(self, image_path: Path) -> bytes:
        """Konvertiert eine Bilddatei zu JPEG-Bytes für die Vision-API."""
        import io
        try:
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                if img.width > self.max_image_size or img.height > self.max_image_size:
                    img.thumbnail((self.max_image_size, self.max_image_size), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.image_quality, optimize=True)
                return buf.getvalue()
        except Exception as e:
            raise ProcessingError(f"Fehler beim Konvertieren der Bilddatei: {e}")

    def _download_image(self, url: str, working_dir: Path) -> Path:
        """Lädt ein Bild von einer URL herunter und gibt den lokalen Pfad zurück."""
        parsed = urlparse(url)
        file_name = parsed.path.split('/')[-1] if parsed.path else ""
        valid_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
        if not file_name or not any(file_name.lower().endswith(ext) for ext in valid_exts):
            file_name = f"downloaded_{int(time.time())}.jpg"

        local_path = working_dir / file_name
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(local_path, 'wb') as f:
                f.write(response.content)
            return local_path
        except Exception as e:
            raise ProcessingError(f"Fehler beim Herunterladen des Bildes: {e}")

    def _validate_image(self, file_path: Path) -> None:
        """Prüft Dateigröße und Auflösung."""
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes (Maximum: {self.max_file_size})"
            )
        with Image.open(file_path) as img:
            w, h = img.size
            if w > self.max_resolution or h > self.max_resolution:
                raise ProcessingError(
                    f"Bildauflösung zu groß: {w}x{h} (Maximum: {self.max_resolution}x{self.max_resolution})"
                )

    # --- Provider-Auflösung ---

    def _resolve_provider_and_model(
        self,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> tuple[LLMProvider, str]:
        """Löst Provider und Modell auf, mit optionalen Overrides."""
        if provider_override:
            from src.core.llm.provider_manager import ProviderManager
            pm = ProviderManager()
            pconfig = self.llm_config_manager.get_provider_config(provider_override)
            if pconfig:
                provider = pm.get_provider(
                    provider_name=provider_override,
                    api_key=pconfig.api_key,
                    base_url=pconfig.base_url,
                    **pconfig.additional_config
                )
            else:
                provider = self.llm_config_manager.get_provider_for_use_case(UseCase.IMAGE_ANALYSIS)
        else:
            provider = self.llm_config_manager.get_provider_for_use_case(UseCase.IMAGE_ANALYSIS)

        if not provider:
            raise ProcessingError(
                "Kein Provider für IMAGE_ANALYSIS konfiguriert. "
                "Bitte 'llm_config.use_cases.image_analysis' in config.yaml setzen."
            )

        model = model_override or (
            self.llm_config_manager.get_model_for_use_case(UseCase.IMAGE_ANALYSIS) or ""
        )
        if not model:
            raise ProcessingError(
                "Kein Modell für IMAGE_ANALYSIS konfiguriert. "
                "Bitte 'llm_config.use_cases.image_analysis.model' in config.yaml setzen."
            )

        return provider, model

    # --- Hauptmethode ---

    def analyze_by_template(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        template_content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        target_language: str = "de",
        use_cache: bool = True,
        file_hash: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        is_url: bool = False
    ) -> TransformerResponse:
        """
        Analysiert ein Bild anhand eines Templates und liefert strukturierte Daten.
        
        Args:
            file_path: Pfad zur Bilddatei oder URL
            template: Name des Templates
            template_content: Direkter Template-Inhalt
            context: Zusätzlicher Kontext
            additional_field_descriptions: Extra Feldbeschreibungen
            target_language: Zielsprache
            use_cache: Cache nutzen
            file_hash: Optional vorkompulierter Hash
            model: Modell-Override
            provider: Provider-Override
            is_url: Ob file_path eine URL ist
        """
        working_dir = self.temp_dir / "working"
        working_dir.mkdir(parents=True, exist_ok=True)
        local_file_path = Path(file_path)

        try:
            # URL herunterladen falls nötig
            if is_url:
                local_file_path = self._download_image(str(file_path), working_dir)

            # Bild validieren
            self._validate_image(local_file_path)

            # Cache prüfen
            cache_key = ""
            if use_cache and self.is_cache_enabled():
                cache_key = self._build_cache_key(
                    file_path=str(file_path),
                    template=template,
                    template_content=template_content,
                    context=context,
                    target_language=target_language,
                    file_hash=file_hash
                )
                hit, cached = self.get_from_cache(cache_key)
                if hit and cached:
                    self.logger.info(f"Cache-Hit für Bildanalyse: {cache_key[:8]}...")
                    return self.create_response(
                        processor_name="image_analyzer",
                        result=cached,
                        request_info=self._request_info(file_path, template, context),
                        response_class=TransformerResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # 1. Template vorbereiten (shared mit WhisperTranscriber)
            tmpl_content, system_prompt, field_defs, required_fields, fm_context_only = (
                template_utils.prepare_template_for_extraction(
                    template_name=template,
                    template_content=template_content,
                    context=context,
                    text="",
                    input_type="image"
                )
            )

            if not field_defs.fields:
                raise ProcessingError("Keine strukturierten Variablen im Template gefunden")

            # 2. Systemprompt mit target_language füllen
            if "{target_language}" in system_prompt:
                system_prompt = system_prompt.replace("{target_language}", target_language)

            # 3. Extraction-Prompt bauen (shared)
            user_prompt = template_utils.build_extraction_prompt(
                context=context,
                required_field_descriptions=required_fields,
                target_language=target_language,
                input_type="image"
            )

            # System- und User-Prompt kombinieren für Vision-API
            # (Vision-API akzeptiert nur einen einzelnen Prompt)
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"

            # 4. Bild konvertieren und Vision-API aufrufen
            image_bytes = self._convert_image_to_bytes(local_file_path)
            vision_provider, vision_model = self._resolve_provider_and_model(provider, model)

            raw_content, llm_request = vision_provider.vision(
                image_data=image_bytes,
                prompt=combined_prompt,
                model=vision_model,
                max_tokens=4000,
                temperature=0.1,
                detail="high"
            )

            # LLM-Tracking
            if llm_request:
                self.add_llm_requests([llm_request])

            # 5. JSON parsen (shared)
            result_json = template_utils.parse_llm_json_response(
                raw_content, field_defs, self.logger
            )

            # 6. Template mit Daten füllen (shared)
            filled_template = template_utils.fill_template_with_data(
                template_content=tmpl_content,
                result_json=result_json,
                field_definitions=field_defs,
                context=context,
                fm_context_only=fm_context_only
            )

            # 7. Ergebnis erstellen
            result = TransformationResult(
                text=filled_template,
                target_language=target_language,
                structured_data=result_json.copy()
            )

            # Cache speichern
            if use_cache and self.is_cache_enabled() and cache_key:
                self.save_to_cache(cache_key, result)

            return self.create_response(
                processor_name="image_analyzer",
                result=TransformerData(
                    text=filled_template,
                    language=target_language,
                    format=OutputFormat.TEXT,
                    structured_data=result_json.copy()
                ),
                request_info=self._request_info(file_path, template, context),
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error(f"Fehler bei der Bildanalyse: {e}")
            return self.create_response(
                processor_name="image_analyzer",
                result=None,
                request_info=self._request_info(file_path, template, context),
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=type(e).__name__,
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )

    # --- Cache-Interface (erforderlich von CacheableProcessor) ---

    def serialize_for_cache(self, result: TransformationResult) -> Dict[str, Any]:
        return {"result": result.to_dict()}

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> TransformationResult:
        return TransformationResult.from_dict(cached_data.get("result", {}))

    # --- Hilfsmethoden ---

    def _build_cache_key(self, **kwargs: Any) -> str:
        """Erzeugt einen Cache-Key aus den relevanten Parametern."""
        parts: list[str] = []
        if kwargs.get("file_hash"):
            parts.append(f"hash_{kwargs['file_hash']}")
        else:
            parts.append(f"path_{kwargs.get('file_path', '')}")
        if kwargs.get("template"):
            parts.append(f"tmpl_{kwargs['template']}")
        if kwargs.get("template_content"):
            tc_hash = hashlib.md5(str(kwargs["template_content"]).encode()).hexdigest()[:8]
            parts.append(f"tc_{tc_hash}")
        if kwargs.get("context"):
            ctx_hash = hashlib.md5(json.dumps(kwargs["context"], sort_keys=True).encode()).hexdigest()[:8]
            parts.append(f"ctx_{ctx_hash}")
        parts.append(f"lang_{kwargs.get('target_language', 'de')}")
        return self.generate_cache_key("_".join(parts))

    @staticmethod
    def _request_info(
        file_path: Union[str, Path],
        template: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return {
            "file_path": str(file_path),
            "template": template,
            "context": context
        }
