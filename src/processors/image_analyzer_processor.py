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
import io
import json
from typing import Any, Dict, List, Optional

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

    # --- Bild-Hilfsfunktionen (in-memory, keine Disk-IO durch unseren Code) ---

    def _resize_image_bytes(self, image_bytes: bytes) -> bytes:
        """
        Resized Eingabe-Bytes auf max_image_size x max_image_size und liefert
        wieder JPEG-Bytes für die Vision-API.

        Vorher arbeitete diese Funktion auf einer Datei vom Pfad. Jetzt
        komplett in-memory: kein Disk-IO im eigenen Code.
        """
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                if img.width > self.max_image_size or img.height > self.max_image_size:
                    img.thumbnail((self.max_image_size, self.max_image_size), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.image_quality, optimize=True)
                return buf.getvalue()
        except Exception as e:
            raise ProcessingError(f"Fehler beim Konvertieren der Bild-Bytes: {e}")

    def _validate_image_bytes(self, image_bytes: bytes) -> None:
        """
        Prüft Dateigröße und Auflösung anhand der Bytes (in-memory).
        Wirft ProcessingError, wenn Limits überschritten sind.
        """
        file_size = len(image_bytes)
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes (Maximum: {self.max_file_size})"
            )
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                w, h = img.size
                if w > self.max_resolution or h > self.max_resolution:
                    raise ProcessingError(
                        f"Bildauflösung zu groß: {w}x{h} (Maximum: {self.max_resolution}x{self.max_resolution})"
                    )
        except ProcessingError:
            raise
        except Exception as e:
            raise ProcessingError(f"Bild konnte nicht gelesen/dekodiert werden: {e}")

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

    # Hartes Limit für Multi-Image: schützt vor übergroßen LLM-Calls und RAM.
    # Bewusst hier als Klassenkonstante, damit es leicht änderbar ist.
    MAX_IMAGES_PER_REQUEST: int = 10

    def analyze_by_template(
        self,
        image_data_list: List[bytes],
        template: Optional[str] = None,
        template_content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        target_language: str = "de",
        use_cache: bool = True,
        file_hashes: Optional[List[str]] = None,
        file_names: Optional[List[str]] = None,
        image_urls: Optional[List[str]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> TransformerResponse:
        """
        Analysiert ein oder mehrere Bilder anhand eines Templates und liefert
        strukturierte Daten.

        Multi-Image: Alle Bilder werden in einem einzigen Vision-Call übergeben
        (siehe docs/multi_image_analyzer.md – Variante 1). Die Reihenfolge
        wird beibehalten und gibt dem LLM Kontext (Seite 1, Seite 2, ...).

        Args:
            image_data_list: Liste der Bild-Bytes (mind. 1, max. MAX_IMAGES_PER_REQUEST).
            template: Name des Templates (alternativ template_content).
            template_content: Direkter Template-Inhalt (alternativ template).
            context: Zusätzlicher Kontext, fließt in System-/User-Prompt + Cache-Key.
            additional_field_descriptions: Extra Feldbeschreibungen (nur Logging).
            target_language: Zielsprache (default 'de').
            use_cache: Wenn True, wird der Cache geprüft/geschrieben.
            file_hashes: Optional, Hashes der Bilder (für Cache-Key + Logging).
                Wenn None, werden Hashes nicht in den Key aufgenommen
                (Cache-Hit ist dann unwahrscheinlich).
            file_names: Optional, Original-Dateinamen (nur Logging).
            image_urls: Optional, Quell-URLs (nur Logging).
            model: Optional Modell-Override.
            provider: Optional Provider-Override.

        Returns:
            TransformerResponse: Erfolgs- oder Fehlerantwort.
        """
        # Validierung der Bild-Liste — fail fast, bevor irgendwas Ressourcen kostet.
        if not image_data_list:
            return self.create_response(
                processor_name="image_analyzer",
                result=None,
                request_info=self._request_info(file_names, image_urls, template, context),
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message="Keine Bilder übergeben (leere Liste).",
                    details={"error_type": "ProcessingError"}
                )
            )
        if len(image_data_list) > self.MAX_IMAGES_PER_REQUEST:
            return self.create_response(
                processor_name="image_analyzer",
                result=None,
                request_info=self._request_info(file_names, image_urls, template, context),
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=(
                        f"Zu viele Bilder: {len(image_data_list)} (Maximum: "
                        f"{self.MAX_IMAGES_PER_REQUEST})"
                    ),
                    details={"error_type": "ProcessingError"}
                )
            )

        try:
            # 1. Bilder validieren (in-memory, keine Disk-IO durch eigenen Code).
            for idx, img_bytes in enumerate(image_data_list):
                try:
                    self._validate_image_bytes(img_bytes)
                except ProcessingError as e:
                    raise ProcessingError(f"Bild #{idx + 1}: {e}") from e

            # Provider/Modell VOR dem Cache-Check auflösen.
            # Grund: Beide fließen in den Cache-Key ein, damit unterschiedliche
            # LLM-Konfigurationen separate Cache-Einträge erzeugen.
            vision_provider, vision_model = self._resolve_provider_and_model(provider, model)
            provider_name = vision_provider.get_provider_name()

            # Eingangsparameter strukturiert loggen (Diagnose / Cache-Key-Auditing).
            # template_content wird gehasht, damit das Log nicht aufgeblasen wird.
            tc_len = len(template_content) if template_content else 0
            tc_hash_log = (
                hashlib.md5(template_content.encode()).hexdigest()[:8]
                if template_content else None
            )
            self.logger.info(
                "ImageAnalyzer: analyze_by_template aufgerufen",
                image_count=len(image_data_list),
                file_names=file_names,
                file_hashes=file_hashes,
                image_urls=image_urls,
                image_bytes_per_image=[len(b) for b in image_data_list],
                template=template,
                template_content_length=tc_len,
                template_content_md5_8=tc_hash_log,
                context=context,
                additional_field_descriptions=additional_field_descriptions,
                target_language=target_language,
                use_cache=use_cache,
                provider_override=provider,
                model_override=model,
                resolved_provider=provider_name,
                resolved_model=vision_model,
            )

            # 2. Cache prüfen.
            cache_key = ""
            if use_cache and self.is_cache_enabled():
                cache_key = self._build_cache_key(
                    template=template,
                    template_content=template_content,
                    context=context,
                    target_language=target_language,
                    file_hashes=file_hashes,
                    provider=provider_name,
                    model=vision_model,
                )
                hit, cached = self.get_from_cache(cache_key)
                if hit and cached:
                    self.logger.info(f"Cache-Hit für Bildanalyse: {cache_key[:8]}...")
                    return self.create_response(
                        processor_name="image_analyzer",
                        result=cached,
                        request_info=self._request_info(file_names, image_urls, template, context),
                        response_class=TransformerResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # 3. Template vorbereiten (shared mit WhisperTranscriber).
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

            # 4. Systemprompt mit target_language füllen.
            if "{target_language}" in system_prompt:
                system_prompt = system_prompt.replace("{target_language}", target_language)

            # 5. Extraction-Prompt bauen (shared).
            user_prompt = template_utils.build_extraction_prompt(
                context=context,
                required_field_descriptions=required_fields,
                target_language=target_language,
                input_type="image"
            )

            # System- und User-Prompt kombinieren für Vision-API
            # (Vision-API akzeptiert nur einen einzelnen Prompt).
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"

            # 6. Alle Bilder resizen / JPEG-normalisieren (in-memory).
            #    Reihenfolge wird beibehalten — relevant für den LLM-Kontext.
            resized_images: List[bytes] = [
                self._resize_image_bytes(img) for img in image_data_list
            ]

            # Hardcoded LLM-Parameter; bei Änderung muss der Cache invalidiert werden.
            vision_max_tokens = 4000
            vision_temperature = 0.1
            vision_detail = "high"

            # Vollständiger Parameter-Log direkt vor dem LLM-Aufruf.
            # Prompts werden bewusst nur als Längen+Snippet geloggt, um
            # vertrauliche Inhalte nicht im Klartext zu protokollieren.
            self.logger.info(
                "ImageAnalyzer: Vision-API-Aufruf",
                provider=provider_name,
                model=vision_model,
                image_count=len(resized_images),
                total_image_bytes=sum(len(b) for b in resized_images),
                system_prompt_length=len(system_prompt),
                user_prompt_length=len(user_prompt),
                combined_prompt_length=len(combined_prompt),
                combined_prompt_snippet=combined_prompt[:300],
                required_fields=list(required_fields.keys()),
                max_tokens=vision_max_tokens,
                temperature=vision_temperature,
                detail=vision_detail,
                target_language=target_language,
                cache_key=cache_key
            )

            # 7. Vision-API mit allen Bildern in einem Call.
            raw_content, llm_request = vision_provider.vision(
                image_data=resized_images,
                prompt=combined_prompt,
                model=vision_model,
                max_tokens=vision_max_tokens,
                temperature=vision_temperature,
                detail=vision_detail
            )

            if llm_request:
                self.add_llm_requests([llm_request])

            # 8. JSON parsen (shared).
            result_json = template_utils.parse_llm_json_response(
                raw_content, field_defs, self.logger
            )

            # 9. Template mit Daten füllen (shared).
            filled_template = template_utils.fill_template_with_data(
                template_content=tmpl_content,
                result_json=result_json,
                field_definitions=field_defs,
                context=context,
                fm_context_only=fm_context_only
            )

            # 10. Ergebnis erstellen.
            result = TransformationResult(
                text=filled_template,
                target_language=target_language,
                structured_data=result_json.copy()
            )

            # 11. Cache speichern.
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
                request_info=self._request_info(file_names, image_urls, template, context),
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error(f"Fehler bei der Bildanalyse: {e}")
            return self.create_response(
                processor_name="image_analyzer",
                result=None,
                request_info=self._request_info(file_names, image_urls, template, context),
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
        """
        Erzeugt einen Cache-Key aus den relevanten Parametern.

        Berücksichtigte Parameter:
        - file_hashes (Liste, Reihenfolge erhalten — andere Reihenfolge der
          Bilder ergibt einen anderen Key, weil das LLM die Reihenfolge als
          Kontext nutzt).
        - template (Name)
        - template_content (gehasht)
        - context (sortiert+gehasht)
        - target_language
        - provider (LLM-Provider-Name, z.B. "openrouter")
        - model (LLM-Modell, z.B. "google/gemini-3-flash-preview")

        WICHTIG: Provider und Modell sind im Key, damit unterschiedliche
        LLM-Konfigurationen separate Cache-Einträge erzeugen.
        Hardcoded Parameter (max_tokens, temperature, detail) sind NICHT im
        Key – Änderungen daran erfordern manuelle Cache-Invalidierung.
        """
        parts: list[str] = []

        # file_hashes: Liste reihenfolgeerhaltend einfließen lassen.
        # Wenn keine Hashes vorliegen, lassen wir den Key absichtlich ohne
        # Bild-Identität — Cache-Hit ist dann unwahrscheinlich, was korrekt
        # ist (wir wissen nicht, ob es dasselbe Bild ist).
        file_hashes = kwargs.get("file_hashes")
        if file_hashes:
            joined = "|".join(str(h) for h in file_hashes)
            fh_hash = hashlib.md5(joined.encode()).hexdigest()[:16]
            parts.append(f"imgs_{len(file_hashes)}_{fh_hash}")
        if kwargs.get("template"):
            parts.append(f"tmpl_{kwargs['template']}")
        if kwargs.get("template_content"):
            tc_hash = hashlib.md5(str(kwargs["template_content"]).encode()).hexdigest()[:8]
            parts.append(f"tc_{tc_hash}")
        if kwargs.get("context"):
            ctx_hash = hashlib.md5(json.dumps(kwargs["context"], sort_keys=True).encode()).hexdigest()[:8]
            parts.append(f"ctx_{ctx_hash}")
        parts.append(f"lang_{kwargs.get('target_language', 'de')}")
        if kwargs.get("provider"):
            parts.append(f"prov_{kwargs['provider']}")
        if kwargs.get("model"):
            parts.append(f"model_{kwargs['model']}")
        return self.generate_cache_key("_".join(parts))

    @staticmethod
    def _request_info(
        file_names: Optional[List[str]],
        image_urls: Optional[List[str]],
        template: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Baut die `request_info` für die Response.

        Liefert eine Liste von Datei-Identifikatoren (Namen oder URLs),
        damit der Aufrufer nachvollziehen kann, welche Bilder analysiert
        wurden. `file_path` (Single-Wert) gibt es nicht mehr.
        """
        return {
            "file_names": file_names,
            "image_urls": image_urls,
            "template": template,
            "context": context,
        }
