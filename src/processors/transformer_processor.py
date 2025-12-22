"""
@fileoverview Transformer Processor - Text transformation with LLM models

@description
Transformer processor module. Handles text transformation using LLM models.
This processor performs various text transformations with LLM models:
- Translation between languages
- Template-based transformation (e.g., meeting minutes, blog article)
- Summarization and structuring of texts
- HTML to Markdown conversion
- Table extraction and formatting

LLM tracking logic:
The processor tracks LLM usage on two levels:
1. Aggregated information (LLMInfo): Total tokens, duration, costs
2. Individual requests (LLMRequest): Per operation with details (model, purpose, tokens, duration)

Features:
- Template-based transformation with custom templates
- Support for various output formats (Markdown, HTML, JSON, etc.)
- Caching of transformation results in MongoDB
- Detailed LLM tracking for cost analysis
- HTML parsing and cleaning
- Table extraction from HTML

@module processors.transformer_processor

@exports
- TransformerProcessor: Class - Text transformation processor

@usedIn
- src.processors.audio_processor: Uses TransformerProcessor for template transformation
- src.processors.pdf_processor: Uses TransformerProcessor for PDF text transformation
- src.processors.session_processor: Uses TransformerProcessor for session documentation
- src.api.routes.transformer_routes: API endpoint for text transformation

@dependencies
- External: openai - OpenAI GPT models for text transformation
- External: beautifulsoup4 - HTML parsing and cleaning
- Internal: src.processors.cacheable_processor - CacheableProcessor base class
- Internal: src.core.config_keys - ConfigKeys for API key management
- Internal: src.core.models.transformer - Transformer models (TransformerResponse, etc.)
- Internal: src.core.config - Configuration
"""
import hashlib
from typing import Dict, Any, Optional, Tuple,List, Union, cast, TYPE_CHECKING
from datetime import datetime, UTC
import traceback
import time
import json
import requests
from urllib.parse import urljoin

from bs4 import BeautifulSoup as BS, Tag
from bs4.element import PageElement

if TYPE_CHECKING:
    from src.core.resource_tracking import ResourceCalculator
else:
    from src.core.resource_tracking import ResourceCalculator

from src.core.models.transformer import (
    TransformationResult
)
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.base import ProcessInfo, ErrorInfo
from src.core.models.transformer import (
    TransformerResponse,  TransformerData
)
from src.core.models.enums import OutputFormat
from .cacheable_processor import CacheableProcessor
from src.core.config import Config

# Type-Alias für bessere Lesbarkeit
TableElement = Tag | PageElement
AttributeValue = str | None

class TransformerProcessor(CacheableProcessor[TransformationResult]):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von Transformationsergebnissen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "transformer_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Zeit für Superklasse-Initialisierung messen
        super_init_start = time.time()
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        super_init_end = time.time()
        
        try:
            # Konfiguration laden
            config_load_start = time.time()
            config = Config()
            processor_config = config.get('processors', {})
            transformer_config = processor_config.get('transformer', {})
            config_load_end = time.time()
            
            # LLM Provider-Konfiguration laden (muss vor Modell-Laden erfolgen)
            from src.core.llm import LLMConfigManager, UseCase
            self.llm_config_manager = LLMConfigManager()
            
            # Modell aus LLM-Config laden (ausschließlich aus config.yaml)
            configured_model = self.llm_config_manager.get_model_for_use_case(UseCase.CHAT_COMPLETION)
            if not configured_model:
                raise ProcessingError(
                    "Kein Modell für Chat-Completion in der LLM-Config konfiguriert. "
                    "Bitte konfigurieren Sie 'llm_config.use_cases.chat_completion.model' in config.yaml"
                )
            self.model: str = configured_model
            
            # Andere Konfigurationswerte aus alter Config-Struktur (nicht LLM-spezifisch)
            self.temperature: float = transformer_config.get('temperature', 0.7)
            self.max_tokens: int = transformer_config.get('max_tokens', 4000)
            self.target_format: OutputFormat = transformer_config.get('target_format', OutputFormat.TEXT)
            
            # Performance-Einstellungen
            self.max_concurrent_requests: int = transformer_config.get('max_concurrent_requests', 10)
            self.timeout_seconds: int = transformer_config.get('timeout_seconds', 120)
            
            # Templates-Verzeichnis
            self.templates_dir: str = transformer_config.get('templates_dir', 'resources/templates')
            
            # Lade Provider für Chat-Completion (ausschließlich aus LLM-Config)
            client_init_start = time.time()
            self.provider = self.llm_config_manager.get_provider_for_use_case(UseCase.CHAT_COMPLETION)
            if not self.provider:
                raise ProcessingError(
                    "Kein Provider für Chat-Completion in der LLM-Config konfiguriert. "
                    "Bitte konfigurieren Sie 'llm_config.use_cases.chat_completion.provider' in config.yaml"
                )
            self.client = self.provider.get_client()
            client_init_end = time.time()
            
            # Initialisiere den Transcriber mit Transformer-spezifischen Konfigurationen
            transcriber_init_start = time.time()
            transcriber_config = {
                'processor_name': 'transformer',
                'cache_dir': str(self.cache_dir),  # Haupt-Cache-Verzeichnis
                'temp_dir': str(self.temp_dir),    # Temporäres Unterverzeichnis
                'debug_dir': str(self.temp_dir / "debug"),  # Debug-Verzeichnis im temp-Bereich
                'model': self.model,
                'temperature': self.temperature,
                'max_tokens': self.max_tokens
            }
            self.transcriber = WhisperTranscriber(transcriber_config, processor=self)
            transcriber_init_end = time.time()
            
            # Debug-Logging der Konfiguration
            self.logger.debug("Transformer Processor initialisiert",
                            model=self.model,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                            target_format=self.target_format,
                            max_concurrent_requests=self.max_concurrent_requests,
                            timeout_seconds=self.timeout_seconds,
                            templates_dir=self.templates_dir)
                            
            # Zeit für Gesamtinitialisierung beenden
            init_end = time.time()
            # Nutze die gemessenen Zeiten für detailliertes Debugging
            try:
                init_timings = {
                    "total_init_ms": round((init_end - init_start) * 1000, 2),
                    "super_init_ms": round((super_init_end - super_init_start) * 1000, 2),
                    "config_load_ms": round((config_load_end - config_load_start) * 1000, 2),
                    "client_init_ms": round((client_init_end - client_init_start) * 1000, 2),
                    "transcriber_init_ms": round((transcriber_init_end - transcriber_init_start) * 1000, 2),
                }
                self.logger.debug("Transformer Init Timings", **init_timings)
            except Exception:
                # Timing-Logging darf keine Exceptions verursachen
                pass
                            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des TransformerProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def _create_cache_key(self, 
                         source_text: str, 
                         source_language: str, 
                         target_language: str, 
                         template: Optional[str] = None,
                         summarize: bool = False) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf den Eingabeparametern.
        
        Args:
            source_text: Der Quelltext
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            template: Optional, das verwendete Template
            summarize: Ob der Text zusammengefasst werden soll
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Für längere Texte nur die ersten 1000 Zeichen und einen Hash verwenden
        if len(source_text) > 1000:
            text_for_key = source_text[:1000] + hashlib.md5(source_text.encode()).hexdigest()
        else:
            text_for_key = source_text
            
        # Basis-Schlüssel aus Text, Sprachen und Modell generieren
        base_key = f"{text_for_key}_{source_language}_{target_language}_{self.model}"
        
        # Zusammenfassung-Flag hinzufügen
        if summarize:
            base_key = f"{base_key}_summarize"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            template_key = hashlib.md5(template.encode()).hexdigest()
            base_key = f"{base_key}_{template_key}"
            
        # Hash generieren
        return self.generate_cache_key(base_key)
    
    def serialize_for_cache(self, result: TransformationResult) -> Dict[str, Any]:
        """
        Serialisiert das TransformationResult für die Speicherung im Cache.
        
        Args:
            result: Das TransformationResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern (keine LLM-Informationen im Cache)
        cache_data = {
            "text": result.text,
            "target_language": result.target_language,
            "structured_data": result.structured_data,
            "cached_at": datetime.now().isoformat(),
            "model": self.model
        }
        
        return cache_data
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> TransformationResult:
        """
        Deserialisiert die Cache-Daten zurück in ein TransformationResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            TransformationResult: Das deserialisierte TransformationResult
        """
        # Filtern Sie nur die bekannten Felder, die in TransformationResult.from_dict akzeptiert werden
        # Dies macht die Deserialisierung robust gegenüber zusätzlichen Feldern
        filtered_data = {
            "text": cached_data.get("text", ""),
            "target_language": cached_data.get("target_language", "unknown"),
            "structured_data": cached_data.get("structured_data"),
            "processed_at": cached_data.get("processed_at", datetime.now(UTC).isoformat())
        }
        
        # TransformationResult aus gefilterten Daten erstellen
        # LLM-Informationen werden bewusst weggelassen, da sie bei Cache-Treffern nicht vorhanden sind
        return TransformationResult.from_dict(filtered_data)
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für die Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        # Index für Zielsprache
        collection.create_index("target_language")
        
        # Index für das verwendete Modell
        collection.create_index("model")
        
        # Index für das Erstellungsdatum
        collection.create_index("cached_at")
    
    def transform(self, 
                 source_text: str, 
                 source_language: str, 
                 target_language: str, 
                 summarize: bool = False, 
                 target_format: Optional[OutputFormat] = None,
                 context: Optional[Dict[str, Any]] = None,
                 use_cache: bool = True) -> TransformerResponse:
        """
        Transformiert einen Text von einer Sprache in eine andere.
        
        Args:
            source_text: Der Quelltext
            source_language: Die Quellsprache (ISO 639-1 Code)
            target_language: Die Zielsprache (ISO 639-1 Code)
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Das Zielformat (TEXT, HTML, MARKDOWN)
            context: Optionaler Kontext für die Transformation
            use_cache: Ob der Cache verwendet werden soll (default: True)
            
        Returns:
            TransformerResponse: Die Antwort mit dem transformierten Text
        """
        process_start = time.time()
        self.logger.info(f"Transformer Process-Methode gestartet")
        
        try:
            # Setze Standardwerte
            if not target_format:
                target_format = self.target_format
            
            # Validiere Parameter
            validation_start = time.time()
            source_text = self.validate_text(source_text)
            validation_end = time.time()
            self.logger.info(f"Zeit für Parameter-Validierung: {(validation_end - validation_start) * 1000:.2f} ms")
            
            # Cache-Schlüssel erstellen
            cache_key_start = time.time()
            cache_key: str = self._create_cache_key(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize
            )
            cache_key_end = time.time()
            self.logger.info(f"Zeit für Cache-Key Generierung: {(cache_key_end - cache_key_start) * 1000:.2f} ms")
            
            # Cache prüfen (wenn aktiviert)
            cache_check_start = time.time()
            cache_hit = False
            cached_result = None
            
            if use_cache and self.is_cache_enabled():
                # Versuche, aus dem MongoDB-Cache zu laden
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Transformation")
                    
                    # Response aus Cache erstellen
                    response_start = time.time()
                    response: TransformerResponse = self._create_response_from_cached_result(
                        cached_result=TransformerData(
                            text=cached_result.text,
                            language=cached_result.target_language,
                            format=self.target_format,
                            summarized=False
                        ),
                        source_text=source_text,
                        source_language=source_language,
                        target_language=target_language,
                        summarize=summarize,
                        target_format=target_format,
                        cache_key=cache_key
                    )
                    response_end = time.time()
                    self.logger.info(f"Zeit für Response-Erstellung aus Cache: {(response_end - response_start) * 1000:.2f} ms")
                    
                    process_end = time.time()
                    self.logger.info(f"Gesamte Process-Zeit (Cache-Hit): {(process_end - process_start) * 1000:.2f} ms")
                    
                    return response
            cache_check_end = time.time()
            self.logger.info(f"Zeit für Cache-Prüfung: {(cache_check_end - cache_check_start) * 1000:.2f} ms")
            
            # Ab hier nur fortfahren, wenn kein Cache-Hit erfolgt ist
            
            # Erstelle Prompt für OpenAI
            prompt_creation_start = time.time()
            system_message, user_prompt = self._create_system_message(
                source_language=source_language,
                target_language=target_language,
                source_text=source_text,
                summarize=summarize,
                target_format=target_format,
                context=context
            )

            prompt_creation_end = time.time()
            self.logger.info(f"Zeit für Prompt-Erstellung: {(prompt_creation_end - prompt_creation_start) * 1000:.2f} ms")
            
            # Text transformieren mit LLM Provider
            llm_call_start = time.time()
            
            # Verwende Provider falls verfügbar
            transformed_text = ""
            llm_request = None
            
            if hasattr(self, 'provider') and self.provider:
                try:
                    transformed_text, llm_request = self.provider.chat_completion(
                        messages=[
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": user_prompt}
                        ],
                        model=self.model,
                        temperature=0.2
                    )
                    
                    llm_call_end = time.time()
                    llm_duration = llm_call_end - llm_call_start
                    self.logger.info(f"Zeit für LLM-Anfrage: {llm_duration * 1000:.2f} ms")
                    
                    # LLM-Nutzung im LLMInfo tracken
                    usage_tracking_start = time.time()
                    if llm_request:
                        self.add_llm_requests([llm_request])
                    usage_tracking_end = time.time()
                    self.logger.debug(f"Zeit für LLM-Tracking: {(usage_tracking_end - usage_tracking_start) * 1000:.2f} ms")
                except Exception as e:
                    # Kein Fallback - Fehler weiterwerfen wie vom Benutzer gewünscht
                    raise ProcessingError(
                        f"Fehler bei der LLM-Anfrage über Provider: {str(e)}"
                    ) from e
            else:
                # Kein Provider konfiguriert - Fehler werfen
                raise ProcessingError(
                    "Kein Provider für Chat-Completion konfiguriert. "
                    "Bitte konfigurieren Sie 'llm_config.use_cases.chat_completion.provider' in config.yaml"
                )
            
            # Erstelle TransformerData
            result_creation_start = time.time()
            transformer_data = TransformerData(
                text=transformed_text,
                language=target_language,
                format=target_format,
                summarized=summarize
            )
            result_creation_end = time.time()
            self.logger.info(f"Zeit für Ergebnis-Erstellung: {(result_creation_end - result_creation_start) * 1000:.2f} ms")
            
            # Im Cache speichern (wenn aktiviert)
            cache_save_start = time.time()
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(
                    cache_key=cache_key,
                    result=TransformationResult(
                        text=transformer_data.text,
                        target_language=transformer_data.language,
                        structured_data=None
                    )
                )
                self.logger.debug(f"Transformer-Ergebnis im Cache gespeichert: {cache_key}")
            cache_save_end = time.time()
            self.logger.info(f"Zeit für Cache-Speicherung: {(cache_save_end - cache_save_start) * 1000:.2f} ms")
            
            # Erstelle die Response mit der ProcessInfo vom BaseProcessor
            response = self.create_response(
                processor_name="transformer",
                result=transformer_data,
                request_info={
                    "source_text": source_text,
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize,
                    "target_format": target_format.value if target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=cache_key
            )
            
            process_end = time.time()
            self.logger.info(f"Gesamte Process-Zeit (ohne Cache): {(process_end - process_start) * 1000:.2f} ms")
            
            return response
            
        except Exception as e:
            self.logger.error("Fehler bei der Transformation",
                              error=e,
                              source_language=source_language,
                              target_language=target_language,
                              summarize=summarize)
            
            error_info = ErrorInfo(
                code="TRANSFORMATION_ERROR",
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize
                }
            )
            
            # Erstelle Error-Response
            return self.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    "source_text": source_text[:100] + "..." if len(source_text) > 100 else source_text,
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize,
                    "target_format": target_format.value if target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

    def _create_system_message(self,
                               source_language: str,
                               target_language: str, 
                               source_text: str,
                               summarize: bool,
                               target_format: Optional[OutputFormat] = None,
                               context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """
        Erstellt die System-Nachricht für den OpenAI-API-Aufruf.
        
        Args:
            source_language: Die Quellsprache (ISO 639-1 Code)
            target_language: Die Zielsprache (ISO 639-1 Code)
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Das gewünschte Ausgabeformat
            context: Zusätzlicher Kontext für die Transformation
            
        Returns:
            str: Die fertige System-Nachricht
        """
        format_instruction = ""
        if target_format == OutputFormat.HTML:
            format_instruction = "Formatiere die Ausgabe als HTML mit korrekten Tags."
        elif target_format == OutputFormat.FILENAME:
            format_instruction = "Formatiere die Ausgabe als gültigen Dateiname ohne Sonderzeichen und Umlaute - ersetze Bindestriche zwischen Worte durch Leerzeichen - max. 50 Zeichen."
        elif target_format == OutputFormat.MARKDOWN:
            format_instruction = "Formatiere die Ausgabe im Markdown-Format."
        
        summarize_instruction = ""
        if summarize:
            summarize_instruction = "Fasse den Text prägnant zusammen, behalte aber alle wichtigen Informationen bei:"
        
        context_instruction = ""
        if context:  # Der Typ Dict[str, Any] garantiert bereits, dass es ein dict ist
            context_str = json.dumps(context, ensure_ascii=False)
            context_instruction = f"Berücksichtige den folgenden Kontext bei der Aufgabe: {context_str}"
        
        system_message: str = f"""Du bist ein Textverarbeitungsassistent, der Texte perfekt übersetzt und formatiert."""        

        # Sprachname aus ISO 639-1 Code ermitteln
        target_language_name = self._get_language_name(target_language)
       
        user_prompt: str = f"""
{summarize_instruction}
{format_instruction}
{context_instruction}
Übersetze das Ergebnis ohne zusätzliche Erklärungen oder Metadaten in die Sprache '{target_language_name}'
Folgender Text soll verarbeitet werden: 

{source_text}
"""

        return system_message, user_prompt

    def _get_language_name(self, language_code: str) -> str:
        """
        Wandelt einen ISO 639-1 Sprachcode in den entsprechenden Sprachnamen um.
        
        Args:
            language_code: ISO 639-1 Sprachcode (z.B. 'de', 'en')
            
        Returns:
            str: Der entsprechende Sprachname oder der Code selbst, falls nicht gefunden
        """
        language_map = {
            "aa": "Afar",
            "ab": "Abchasisch",
            "af": "Afrikaans",
            "am": "Amharisch",
            "ar": "Arabisch",
            "as": "Assamesisch",
            "ay": "Aymara",
            "az": "Aserbaidschanisch",
            "ba": "Baschkirisch",
            "be": "Belarussisch",
            "bg": "Bulgarisch",
            "bh": "Biharisch",
            "bi": "Bislama",
            "bn": "Bengalisch",
            "bo": "Tibetisch",
            "br": "Bretonisch",
            "ca": "Katalanisch",
            "co": "Korsisch",
            "cs": "Tschechisch",
            "cy": "Walisisch",
            "da": "Dänisch",
            "de": "Deutsch",
            "dz": "Dzongkha",
            "el": "Griechisch",
            "en": "Englisch",
            "eo": "Esperanto",
            "es": "Spanisch",
            "et": "Estnisch",
            "eu": "Baskisch",
            "fa": "Persisch",
            "fi": "Finnisch",
            "fj": "Fidschi",
            "fo": "Färöisch",
            "fr": "Französisch",
            "fy": "Friesisch",
            "ga": "Irisch",
            "gd": "Schottisches Gälisch",
            "gl": "Galizisch",
            "gn": "Guaraní",
            "gu": "Gujarati",
            "ha": "Hausa",
            "he": "Hebräisch",
            "hi": "Hindi",
            "hr": "Kroatisch",
            "hu": "Ungarisch",
            "hy": "Armenisch",
            "ia": "Interlingua",
            "id": "Indonesisch",
            "ie": "Interlingue",
            "ik": "Inupiaq",
            "is": "Isländisch",
            "it": "Italienisch",
            "iu": "Inuktitut",
            "ja": "Japanisch",
            "jw": "Javanisch",
            "ka": "Georgisch",
            "kk": "Kasachisch",
            "kl": "Grönländisch",
            "km": "Khmer",
            "kn": "Kannada",
            "ko": "Koreanisch",
            "ks": "Kaschmiri",
            "ku": "Kurdisch",
            "ky": "Kirgisisch",
            "la": "Latein",
            "ln": "Lingala",
            "lo": "Lao",
            "lt": "Litauisch",
            "lv": "Lettisch",
            "mg": "Malagasy",
            "mi": "Maori",
            "mk": "Mazedonisch",
            "ml": "Malayalam",
            "mn": "Mongolisch",
            "mo": "Moldawisch",
            "mr": "Marathi",
            "ms": "Malaiisch",
            "mt": "Maltesisch",
            "my": "Burmesisch",
            "na": "Nauruisch",
            "ne": "Nepalesisch",
            "nl": "Niederländisch",
            "no": "Norwegisch",
            "oc": "Okzitanisch",
            "om": "Oromo",
            "or": "Oriya",
            "pa": "Punjabi",
            "pl": "Polnisch",
            "ps": "Paschtu",
            "pt": "Portugiesisch",
            "qu": "Quechua",
            "rm": "Rätoromanisch",
            "rn": "Rundi",
            "ro": "Rumänisch",
            "ru": "Russisch",
            "rw": "Kinyarwanda",
            "sa": "Sanskrit",
            "sd": "Sindhi",
            "sg": "Sango",
            "sh": "Serbo-Kroatisch",
            "si": "Singhalesisch",
            "sk": "Slowakisch",
            "sl": "Slowenisch",
            "sm": "Samoanisch",
            "sn": "Shona",
            "so": "Somali",
            "sq": "Albanisch",
            "sr": "Serbisch",
            "ss": "Swati",
            "st": "Sotho",
            "su": "Sundanesisch",
            "sv": "Schwedisch",
            "sw": "Suaheli",
            "ta": "Tamil",
            "te": "Telugu",
            "tg": "Tadschikisch",
            "th": "Thailändisch",
            "ti": "Tigrinya",
            "tk": "Turkmenisch",
            "tl": "Tagalog",
            "tn": "Tswana",
            "to": "Tongaisch",
            "tr": "Türkisch",
            "ts": "Tsonga",
            "tt": "Tatarisch",
            "tw": "Twi",
            "ug": "Uigurisch",
            "uk": "Ukrainisch",
            "ur": "Urdu",
            "uz": "Usbekisch",
            "vi": "Vietnamesisch",
            "vo": "Volapük",
            "wo": "Wolof",
            "xh": "Xhosa",
            "yi": "Jiddisch",
            "yo": "Yoruba",
            "za": "Zhuang",
            "zh": "Chinesisch",
            "zu": "Zulu"
        }
        
        return language_map.get(language_code.lower(), language_code)

    def validate_text(self, text: Optional[str], field_name: str = "text") -> str:
        """
        Validiert den Eingabetext.
        
        Args:
            text: Der zu validierende Text
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Text
        
        Raises:
            ValueError: Wenn der Text leer ist oder zu lang
        """
        # Rufe die Basismethode auf
        result = super().validate_text(text, field_name)
        
        # Zusätzliche Validierung für die maximale Länge
        if result and len(result) > 100000:
            raise ValueError(f"Der {field_name} ist zu lang: {len(result)} Zeichen (maximal 100.000)")
        
        return result
        
    def _create_response_from_cached_result(self,
                                           cached_result: Union[Dict[str, Any], TransformerData],
                                           source_text: str,
                                           source_language: str,
                                           target_language: str,
                                           summarize: bool,
                                           cache_key: str,
                                           target_format: Optional[OutputFormat]) -> TransformerResponse:
        """
        Erstellt eine TransformerResponse aus einem gecachten Ergebnis.
        
        Args:
            cached_result: Das gecachte Ergebnis (als Dict oder TransformerData)
            source_text: Der Quelltext
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            summarize: Ob der Text zusammengefasst wurde
            target_format: Das Zielformat
            
        Returns:
            TransformerResponse: Die erstellte Response
        """
        # Deserialisiere das gecachte Ergebnis je nach Typ
        transformer_data: TransformerData
        if isinstance(cached_result, dict):
            text = cast(str, cached_result.get("text", ""))
            target_lang = cast(str, cached_result.get("language", target_language))
            format_value = cast(str, cached_result.get("format", target_format.value if target_format else OutputFormat.TEXT.value))
            
            transformer_data = TransformerData(
                text=text,
                language=target_lang,
                format=OutputFormat(format_value),
                summarized=summarize
            )
        else:
            # Es ist bereits ein TransformerData
            transformer_data = cached_result
        
        self.process_info.cache_key= cache_key
        self.process_info.is_from_cache= True        

        # Erstelle Response
        return self.create_response(
            processor_name="transformer",
            result=transformer_data,
            request_info={
                "source_text": source_text,
                "source_language": source_language,
                "target_language": target_language,
                "summarize": summarize,
                "target_format": target_format.value if target_format else None
            },
            response_class=TransformerResponse,
            from_cache=True,
            cache_key=cache_key
        )

    def _extract_clean_text_from_html(self, html: str) -> str:
        """
        Bereinigt HTML-Code und behält alle Struktur-Elemente bei.
        
        Entfernt NUR:
        - Skripte und Styles (script, style) - CSS/JS Code
        - Meta-Tags im Head (meta, link für Stylesheets)
        - SVG-Grafiken (meist nur Icons)
        - noscript-Tags (redundant nach Script-Entfernung)
        
        Behält ALLE Struktur-Elemente:
        - Alle HTML-Struktur-Tags (div, section, article, main, aside, header, footer, nav, etc.)
        - Listen (ul, ol, li)
        - Überschriften (h1-h6)
        - Absätze (p)
        - Alle anderen HTML-Tags und deren Attribute
        
        Die HTML-Struktur wird als bereinigtes HTML mit sichtbaren Tags zurückgegeben,
        damit das LLM die Hierarchie und Struktur erkennen kann.
        
        Args:
            html: Roher HTML-Text
            
        Returns:
            Bereinigtes HTML mit allen Struktur-Tags (nur Body-Bereich)
        """
        soup = BS(html, 'html.parser')

        # Entferne NUR CSS/JS: Skripte und Styles
        for tag_name in ['script', 'style']:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Entferne Meta-Tags im Head (nicht im Body, da diese zur Struktur gehören könnten)
        head = soup.find('head')
        if head:
            for tag_name in ['meta', 'link']:
                for tag in head.find_all(tag_name):
                    tag.decompose()

        # Entferne SVG-Grafiken (meist nur Icons, keine Struktur-Information)
        for tag in soup.find_all('svg'):
            tag.decompose()

        # Entferne noscript-Tags (redundant nach Script-Entfernung)
        for tag in soup.find_all('noscript'):
            tag.decompose()

        # Extrahiere den Body-Bereich (Hauptinhalt der Seite)
        # Falls kein Body vorhanden, verwende das gesamte Dokument
        body = soup.find('body')
        if body:
            # Konvertiere Body zu String mit erhaltener HTML-Struktur
            clean_html: str = str(body)
        else:
            # Falls kein Body-Tag vorhanden, verwende das gesamte bereinigte Dokument
            clean_html = str(soup)
        
        return clean_html

    def _extract_snippets_with_selector(
        self,
        html: str,
        container_selector: str,
        max_snippets: int = 50
    ) -> List[str]:
        """
        Extrahiert HTML-Snippets mit einem gegebenen CSS-Selector.
        
        Args:
            html: HTML-Text
            container_selector: CSS-Selector für die Container (z.B. "li.single-element")
            max_snippets: Maximale Anzahl Snippets
            
        Returns:
            Liste von HTML-Snippets
        """
        soup = BS(html, 'html.parser')
        containers = soup.select(container_selector)
        
        self.logger.info(f"Gefundene Container mit Selector '{container_selector}': {len(containers)}")
        
        snippets = []
        for container in containers[:max_snippets]:
            snippet = str(container)
            if len(snippet) > 100:  # Mindestgröße
                snippets.append(snippet)
        
        self.logger.info(f"Extrahiert: {len(snippets)} Snippets für LLM-Analyse")
        return snippets

    def _find_representative_html_snippets(
        self,
        html: str,
        max_chars: int = 5000,
        min_snippets: int = 3,
        max_snippets: int = 5
    ) -> List[str]:
        """
        Findet automatisch repräsentative HTML-Snippets aus verschiedenen Bereichen der Seite.
        
        Strategie:
        1. Analysiert mehrere Bereiche der Seite (Anfang, Mitte, Ende)
        2. Filtert Menüeinträge und Navigation aus
        3. Sucht nach wiederkehrenden Containern (z.B. li.single-element, div.event-card)
        4. Extrahiert repräsentative Snippets aus verschiedenen Bereichen
        
        Args:
            html: HTML-Text
            max_chars: Maximale Anzahl Zeichen pro Bereich für Analyse
            min_snippets: Minimale Anzahl Snippets
            max_snippets: Maximale Anzahl Snippets
            
        Returns:
            Liste von HTML-Snippets
        """
        html_length = len(html)
        snippets: List[str] = []
        
        # Definiere Bereiche der Seite zu analysieren
        # Für sehr lange Seiten: Anfang, Mitte, Ende
        if html_length > 100000:
            # Sehr lange Seite: 3 Bereiche analysieren
            chunk_size = min(max_chars, html_length // 3)
            areas = [
                (0, chunk_size),  # Anfang
                (html_length // 2 - chunk_size // 2, html_length // 2 + chunk_size // 2),  # Mitte
                (html_length - chunk_size, html_length)  # Ende
            ]
        elif html_length > 50000:
            # Mittlere Seite: 2 Bereiche (Anfang + Mitte)
            chunk_size = min(max_chars, html_length // 2)
            areas = [
                (0, chunk_size),  # Anfang
                (html_length // 2 - chunk_size // 2, html_length // 2 + chunk_size // 2)  # Mitte
            ]
        else:
            # Kurze Seite: Nur Anfang
            areas = [(0, min(max_chars, html_length))]
        
        # Klassen, die typischerweise Menüeinträge/Navigation sind
        menu_exclude_classes = {'menu-item', 'menu-home', 'menu', 'nav', 'navigation', 'header', 'footer', 'social-menu'}
        
        # Analysiere jeden Bereich
        for start_idx, end_idx in areas:
            sample_html = html[start_idx:end_idx]
            soup = BS(sample_html, 'html.parser')
            
            # Strategie 1: Suche nach häufigen Container-Klassen
            all_elements = soup.find_all(True)
            class_counts: Dict[str, int] = {}
            
            for elem in all_elements:
                classes_attr = elem.get('class')
                classes = classes_attr if isinstance(classes_attr, list) else []
                if classes:
                    for cls in classes:
                        if cls and cls not in menu_exclude_classes:
                            class_counts[cls] = class_counts.get(cls, 0) + 1
            
            # Finde Klassen, die häufig vorkommen (mindestens 3x)
            common_classes = [
                cls for cls, count in class_counts.items() 
                if count >= 3
            ]
            
            # Sortiere nach Häufigkeit
            common_classes.sort(key=lambda x: class_counts[x], reverse=True)
            
            # Versuche Container mit diesen Klassen zu finden
            for common_class in common_classes[:10]:  # Top 10 Klassen pro Bereich
                containers = soup.find_all(class_=common_class)
                
                # Filtere Menüeinträge aus
                filtered_containers = []
                for c in containers:
                    classes_attr = c.get('class')
                    classes = classes_attr if isinstance(classes_attr, list) else []
                    classes_str = str(classes)
                    if not any(exclude_cls in classes_str for exclude_cls in menu_exclude_classes):
                        filtered_containers.append(c)
                
                if len(filtered_containers) >= 3:
                    # Nimm mehrere Container aus diesem Bereich
                    for container in filtered_containers[:max_snippets // len(areas) + 5]:
                        snippet = str(container)
                        # Mindestgröße für sinnvolles Snippet, aber nicht zu groß
                        if 100 < len(snippet) < 3000:
                            snippets.append(snippet)
                            if len(snippets) >= max_snippets:
                                break
                
                if len(snippets) >= max_snippets:
                    break
            
            if len(snippets) >= max_snippets:
                break
        
        # Strategie 2: Falls noch nicht genug, suche nach spezifischen Strukturen
        if len(snippets) < min_snippets:
            full_soup = BS(html, 'html.parser')
            
            # Suche nach li-Elementen, die nicht im Menü sind
            list_items = full_soup.find_all('li')
            for li in list_items:
                # Prüfe ob es ein Menü-Eintrag ist
                classes_attr = li.get('class')
                classes = classes_attr if isinstance(classes_attr, list) else []
                classes_str = str(classes)
                if any(exclude_cls in classes_str for exclude_cls in menu_exclude_classes):
                    continue
                
                snippet = str(li)
                if 100 < len(snippet) < 3000:
                    snippets.append(snippet)
                    if len(snippets) >= max_snippets:
                        break
        
        # Strategie 3: Suche nach spezifischen Content-Klassen im gesamten HTML
        if len(snippets) < min_snippets:
            full_soup = BS(html, 'html.parser')
            # Suche nach Elementen mit spezifischen Klassen, die auf Content hinweisen
            # PRIORITÄT: single-element ist der Haupt-Container für Event-Einträge
            content_classes = {'single-element', 'event', 'session', 'item', 'card', 'entry', 'post', 'program-days'}
            
            # PRIORITÄT 1: Suche gezielt nach li.single-element (Haupt-Container)
            li_single_elements = full_soup.find_all('li', class_='single-element')
            if len(li_single_elements) >= min_snippets:
                self.logger.info(f"Gefundene li.single-element Container: {len(li_single_elements)}")
                for li in li_single_elements[:max_snippets]:
                    # Prüfe ob es ein Menü-Eintrag ist
                    classes_attr = li.get('class')
                    classes = classes_attr if isinstance(classes_attr, list) else []
                    classes_str = str(classes)
                    if any(exclude_cls in classes_str for exclude_cls in menu_exclude_classes):
                        continue
                    
                    snippet = str(li)
                    if 200 < len(snippet) < 5000:  # Größere Mindestgröße für Content
                        snippets.append(snippet)
                        if len(snippets) >= max_snippets:
                            break
                if len(snippets) >= min_snippets:
                    # Wir haben genug gute Snippets gefunden
                    return snippets[:max_snippets]
            
            # PRIORITÄT 2: Suche nach anderen li-Elementen mit Content-Klassen (nicht Menü)
            for content_class in content_classes:
                if content_class == 'single-element':
                    continue  # Bereits oben behandelt
                
                # Suche nach li-Elementen mit dieser Klasse
                li_elements = full_soup.find_all('li', class_=content_class)
                for li in li_elements:
                    # Prüfe ob es ein Menü-Eintrag ist
                    classes_attr = li.get('class')
                    classes = classes_attr if isinstance(classes_attr, list) else []
                    classes_str = str(classes)
                    if any(exclude_cls in classes_str for exclude_cls in menu_exclude_classes):
                        continue
                    
                    snippet = str(li)
                    if 200 < len(snippet) < 5000:  # Größere Mindestgröße für Content
                        snippets.append(snippet)
                        if len(snippets) >= max_snippets:
                            break
                if len(snippets) >= max_snippets:
                    break
            
            # Falls immer noch nicht genug, suche nach divs mit Content-Klassen
            if len(snippets) < min_snippets:
                for content_class in content_classes:
                    divs = full_soup.find_all('div', class_=content_class)
                    for div in divs[:max_snippets]:
                        snippet = str(div)
                        if 200 < len(snippet) < 3000:
                            snippets.append(snippet)
                            if len(snippets) >= max_snippets:
                                break
                    if len(snippets) >= max_snippets:
                        break
        
        # Filtere Snippets: Entferne solche, die nur Links/Buttons sind (zu klein oder nur <a>-Tags)
        filtered_snippets = []
        for snippet in snippets:
            snippet_soup = BS(snippet, 'html.parser')
            
            # Prüfe ob das Snippet hauptsächlich aus Links besteht
            links = snippet_soup.find_all('a')
            text_content = snippet_soup.get_text(strip=True)
            
            # Wenn mehr als 50% des Inhalts Links sind oder sehr wenig Text vorhanden, überspringe
            if len(links) > 0 and len(text_content) < 50:
                continue
            
            # Prüfe ob es ein sehr kleines Element ist (wahrscheinlich nur ein Link)
            if len(snippet) < 200:
                # Prüfe ob es hauptsächlich ein <a>-Tag ist
                if snippet_soup.find('a') and len(snippet_soup.find_all()) <= 2:
                    continue
            
            filtered_snippets.append(snippet)
        
        # Entferne Duplikate (basierend auf ersten 100 Zeichen)
        seen = set()
        unique_snippets = []
        for snippet in filtered_snippets:
            snippet_hash = snippet[:100]
            if snippet_hash not in seen:
                seen.add(snippet_hash)
                unique_snippets.append(snippet)
        
        return unique_snippets[:max_snippets]

    def _extract_selectors_with_llm(
        self,
        html_snippets: List[str],
        field_descriptions: Dict[str, str],
        source_language: str = "de",
        use_cache: bool = True,
        container_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ermittelt CSS/XPath-Selectors für strukturierte Daten-Extraktion mit LLM.
        
        Args:
            html_snippets: Liste von HTML-Snippets (typische Einträge)
            field_descriptions: Dict mit Feldnamen und Beschreibungen
            source_language: Sprache für den Prompt
            use_cache: Ob Cache verwendet werden soll
            container_selector: Optional bereits bekannter Container-Selector
            
        Returns:
            Dict mit container-Selector und field-Selectors (xpath/css)
        """
        if not html_snippets:
            raise ProcessingError("Keine HTML-Snippets zum Analysieren")
        
        if not field_descriptions:
            raise ProcessingError("Keine Feldbeschreibungen vorhanden")
        
        # Prompt zusammenstellen
        snippets_text = "\n\n".join([
            f"HTML_SNIPPET_{i+1}:\n{snippet}"
            for i, snippet in enumerate(html_snippets)
        ])
        
        fields_text = "\n".join([
            f"- {name}: {description}"
            for name, description in field_descriptions.items()
        ])
        
        system_prompt = """Du bist ein Experte für HTML-Strukturanalyse und CSS/XPath-Selector-Erstellung.
Deine Aufgabe ist es, aus HTML-Snippets robuste Selectors zu ermitteln, die alle ähnlichen Einträge auf einer Webseite finden können.

KRITISCH WICHTIG: 
- Der Container-Selector muss den ÄUßERSTEN Container finden, der ALLE Felder umschließt
- Typischerweise ist das ein <li> oder <div> Element mit einer spezifischen Klasse (z.B. li.single-element)
- NICHT einzelne Links, Buttons, Bilder oder andere Unterelemente!
- Der Container sollte mehrere Informationen enthalten: Titel, Zeit, Ort, Beschreibung, etc."""
        
        # Prompt zusammenstellen - unterschiedlich je nachdem ob Container-Selector bekannt ist
        if container_selector:
            # Container-Selector ist bereits bekannt - nur Field-Selectors ermitteln
            user_prompt = f"""Hier sind mehrere HTML-Snippets von Event-Einträgen einer Webseite.
Jedes Snippet ist bereits ein vollständiger Event-Container.

{snippets_text}

Ich möchte aus jedem Event folgende Felder extrahieren:
{fields_text}

Aufgabe:
1. Analysiere die HTML-Struktur jedes Snippets.
2. Für jedes Feld sollst du:
   - Einen relativen XPath angeben (ausgehend vom Event-Container, beginnend mit ".//").
   - Einen relativen CSS-Selector angeben (ausgehend vom Event-Container, ohne führenden Selektor).

3. Gib das Ergebnis in folgendem JSON-Format zurück (ohne Kommentare):

{{
  "fields": {{
    "field1": {{ "xpath": "...", "css": "..." }},
    "field2": {{ "xpath": "...", "css": "..." }}
  }},
  "exampleExtractionFromSnippet1": {{
    "field1": "...",
    "field2": "..."
  }}
}}

Anforderungen:
- Container-Selector ist bereits bekannt: {container_selector}
- Verwende möglichst robuste Selector (z.B. Klassen oder data-Attribute), keine reinen Positions-Selector
- XPath bitte relativ zum Container, beginnend mit ".//"
- CSS bitte relativ zum Container, beginnend ohne führenden Selektor (z.B. "h2.element-title a")
- Wenn ein Feld nicht eindeutig bestimmbar ist, gib "null" für xpath und css zurück"""
        else:
            # Container-Selector muss noch ermittelt werden (Fallback für alte Logik)
            user_prompt = f"""Hier sind mehrere HTML-Snippets von Event-Einträgen einer Webseite.

{snippets_text}

Ich möchte aus jedem Event folgende Felder extrahieren:
{fields_text}

Aufgabe:
1. Analysiere die HTML-Struktur und identifiziere den ÄUßERSTEN Container, der alle Felder umschließt.
   Beispiel-Struktur:
   - <li class="single-element">  ← DAS ist der Container!
     - <div class="hour">10:30</div>
     - <div class="inner-element">
       - <h2 class="element-title"><a>...</a></h2>  ← Titel
       - <span class="location">...</span>  ← Ort
       - etc.
   
   Der Container ist NICHT:
   - Ein einzelner <a> Link
   - Ein <div class="image-container"> (nur für Bilder)
   - Ein <button> oder <a class="btn">
   - Ein <span> oder <p> Element
   
2. Leite einen robusten Container-Selector ab, der alle Event-Einträge findet.
   Der Selector sollte auf dem äußersten Container basieren (z.B. "li.single-element").
   
3. Für jedes Feld sollst du:
   - Einen relativen XPath angeben (ausgehend vom Event-Container, beginnend mit ".//").
   - Einen relativen CSS-Selector angeben (ausgehend vom Event-Container, ohne führenden Selektor).

4. Gib das Ergebnis in folgendem JSON-Format zurück (ohne Kommentare):

{{
  "container": {{
    "xpath": "...",
    "css": "..."
  }},
  "fields": {{
    "field1": {{ "xpath": "...", "css": "..." }},
    "field2": {{ "xpath": "...", "css": "..." }}
  }},
  "exampleExtractionFromSnippet1": {{
    "field1": "...",
    "field2": "..."
  }}
}}

Anforderungen:
- Container-Selector MUSS der äußerste Container sein (z.B. "li.single-element"), der mehrere Felder enthält
- Verwende möglichst robuste Selector (z.B. Klassen oder data-Attribute), keine reinen Positions-Selector
- XPath bitte relativ zum Container, beginnend mit ".//"
- CSS bitte relativ zum Container, beginnend ohne führenden Selektor (z.B. "h2.element-title a")
- Wenn ein Feld nicht eindeutig bestimmbar ist, gib "null" für xpath und css zurück"""
        
        # LLM aufrufen - verwende get_structured_data für JSON-Output
        try:
            selectors = self.transcriber.get_structured_data(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                purpose="extract_selectors",
                logger=self.logger,
                processor="transformer"
            )
            
            # Validiere dass fields vorhanden sind
            if "fields" not in selectors:
                raise ProcessingError("LLM-Antwort enthält keine 'fields'-Selectors")
            
            # Wenn Container-Selector bereits bekannt ist, setze ihn
            if container_selector:
                selectors["container"] = {
                    "css": container_selector,
                    "xpath": self._css_to_xpath(container_selector)
                }
                self.logger.info(f"Verwende gegebenen Container-Selector: {container_selector}")
            else:
                # Container-Selector muss vom LLM ermittelt werden (Fallback)
                if "container" not in selectors:
                    raise ProcessingError("LLM-Antwort enthält keinen 'container'-Selector")
                
                # Validiere dass der Container-Selector nicht zu spezifisch ist (z.B. image-container, btn, etc.)
                container_css = selectors.get("container", {}).get("css", "")
                invalid_container_patterns = ['image-container', 'btn', 'link', 'button', 'img', 'figure', 'a[', 'span.', 'p.']
                container_lower = container_css.lower()
                if any(pattern in container_lower for pattern in invalid_container_patterns):
                    self.logger.warning(
                        f"Container-Selector '{container_css}' sieht nach einem Unterelement aus, nicht nach dem Haupt-Container. "
                        f"Versuche Fallback zu 'li.single-element'"
                    )
                    # Fallback: Versuche li.single-element
                    selectors["container"]["css"] = "li.single-element"
                    selectors["container"]["xpath"] = ".//li[contains(@class, 'single-element')]"
                    self.logger.info(f"Verwende Fallback-Selector: li.single-element")
            
            # Debug: Logge die ermittelten Selectors
            container_css = selectors.get("container", {}).get("css", "")
            self.logger.info(f"Ermittelte Selectors - Container CSS: {container_css}")
            self.logger.debug(f"Vollständige Selectors: {json.dumps(selectors, indent=2, ensure_ascii=False)}")
            
            return selectors
            
        except Exception as e:
            error_msg = f"Fehler bei Selector-Ermittlung: {str(e)}"
            self.logger.error(error_msg)
            raise ProcessingError(error_msg) from e

    def _css_to_xpath(self, css_selector: str) -> str:
        """
        Konvertiert einen einfachen CSS-Selector zu XPath.
        
        Args:
            css_selector: CSS-Selector (z.B. "li.single-element")
            
        Returns:
            XPath-String (z.B. ".//li[contains(@class, 'single-element')]")
        """
        # Einfache Konvertierung für häufige Fälle
        if '.' in css_selector:
            parts = css_selector.split('.')
            tag = parts[0] if parts[0] else '*'
            classes = parts[1:]
            if classes:
                class_conditions = ' and '.join([f"contains(@class, '{cls}')" for cls in classes])
                return f".//{tag}[{class_conditions}]"
        return f".//{css_selector}"

    def _scrape_with_selectors(
        self,
        html: str,
        selectors: Dict[str, Any],
        source_url: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Extrahiert strukturierte Daten aus HTML mit gegebenen Selectors.
        
        Args:
            html: HTML-Text
            selectors: Dict mit container und fields (aus _extract_selectors_with_llm)
            source_url: Basis-URL für relative Links
            
        Returns:
            Liste von Dicts mit extrahierten Daten
        """
        soup = BS(html, 'html.parser')
        results = []
        
        # Container finden
        container_css = selectors.get("container", {}).get("css")
        if not container_css:
            raise ProcessingError("Kein Container-CSS-Selector gefunden")
        
        self.logger.info(f"Suche Container mit CSS-Selector: {container_css}")
        containers = soup.select(container_css)
        self.logger.info(f"Gefundene Container: {len(containers)}")
        
        # Wenn zu wenige Container gefunden wurden, versuche alternative Strategien
        if len(containers) < 10:
            self.logger.warning(f"Nur {len(containers)} Container gefunden - versuche alternative Strategien")
            
            # Strategie 1: Versuche Selector ohne spezifische Klassen zu erweitern
            # Z.B. wenn "li.single-element" zu wenig findet, versuche "li" mit Filterung
            if '.' in container_css:
                # Extrahiere Basis-Tag (z.B. "li" aus "li.single-element")
                base_tag = container_css.split('.')[0].split()[0]
                if base_tag:
                    all_base_elements = soup.find_all(base_tag)
                    self.logger.info(f"Alternative: Gefundene {base_tag}-Elemente: {len(all_base_elements)}")
                    
                    # Wenn deutlich mehr Basis-Elemente gefunden wurden, verwende diese mit Filterung
                    if len(all_base_elements) > len(containers) * 3:
                        self.logger.info(f"Verwende erweiterten Selector: {base_tag} (gefiltert)")
                        # Versuche die Klasse aus dem ursprünglichen Selector zu extrahieren
                        class_part = container_css.split('.')[1] if '.' in container_css else None
                        if class_part:
                            # Filtere nach Klasse
                            filtered_containers = [
                                elem for elem in all_base_elements
                                if class_part in str(elem.get('class', []))
                            ]
                            if len(filtered_containers) > len(containers):
                                self.logger.info(f"Gefilterte Container: {len(filtered_containers)}")
                                containers = filtered_containers
            
            # Strategie 2: Versuche breiteren Selector
            # Wenn der Selector eine Klasse enthält, versuche ohne die Klasse
            if len(containers) < 10 and '.' in container_css:
                # Versuche Basis-Tag ohne Klasse
                base_tag = container_css.split('.')[0].strip()
                if base_tag and base_tag in ['li', 'div', 'article', 'section']:
                    all_base = soup.find_all(base_tag)
                    self.logger.info(f"Breiterer Selector '{base_tag}': {len(all_base)} Elemente gefunden")
                    
                    # Wenn deutlich mehr gefunden, verwende diese mit zusätzlicher Filterung
                    if len(all_base) > len(containers) * 2:
                        # Versuche die Klasse aus dem ursprünglichen Selector zu extrahieren
                        class_name = container_css.split('.')[1].split()[0] if '.' in container_css else None
                        if class_name:
                            # Filtere nach Klasse, aber weniger strikt
                            filtered = [
                                elem for elem in all_base
                                if class_name in str(elem.get('class', []))
                            ]
                            if len(filtered) > len(containers):
                                self.logger.info(f"Gefilterte Container mit Klasse '{class_name}': {len(filtered)}")
                                containers = filtered
        
        if len(containers) == 0:
            raise ProcessingError(f"Keine Container mit Selector '{container_css}' gefunden")
        
        # Validiere dass die gefundenen Container nicht nur Menüeinträge sind
        menu_exclude_classes = {'menu-item', 'menu-home', 'menu', 'nav', 'navigation', 'header', 'footer', 'social-menu'}
        non_menu_containers = []
        for container in containers:
            classes_attr = container.get('class')
            classes = classes_attr if isinstance(classes_attr, list) else []
            classes_str = str(classes)
            if not any(exclude_cls in classes_str for exclude_cls in menu_exclude_classes):
                non_menu_containers.append(container)
        
        if len(non_menu_containers) > len(containers) * 0.5:
            # Wenn mehr als die Hälfte nicht-Menü sind, verwende diese
            self.logger.info(f"Gefilterte Container (ohne Menü): {len(non_menu_containers)} von {len(containers)}")
            containers = non_menu_containers
        
        # Für jeden Container die Felder extrahieren
        for container in containers:
            item: Dict[str, Any] = {}
            
            for field_name, field_selectors in selectors.get("fields", {}).items():
                css_selector = field_selectors.get("css")
                
                if not css_selector or css_selector == "null":
                    item[field_name] = None
                    continue
                
                # CSS-Selector relativ zum Container
                element = container.select_one(css_selector)
                
                if element:
                    # Prüfe ob es ein Link ist
                    if element.name == 'a':
                        href_attr = element.get('href', '')
                        href = str(href_attr) if href_attr else ''
                        if href:
                            item[field_name] = urljoin(source_url, href) if source_url else href
                        else:
                            item[field_name] = element.get_text(strip=True)
                    else:
                        item[field_name] = element.get_text(strip=True)
                else:
                    item[field_name] = None
            
            # Nur hinzufügen wenn mindestens ein Feld gefüllt ist
            if any(v is not None and v != "" for v in item.values()):
                results.append(item)
        
        return results

    def transformByUrl(
        self,
        url: str,
        source_language: str,
        target_language: str,
        template: Optional[str] = None,
        template_content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        use_selector_extraction: bool = True,
        container_selector: Optional[str] = None
    ) -> TransformerResponse:
        """
        Transformiert Webseiten-Inhalt nach einem Template.
        
        Wenn use_selector_extraction=True und strukturierte Felder vorhanden sind,
        wird automatisch der zweistufige Ansatz verwendet:
        1. HTML-Snippets werden mit container_selector extrahiert
        2. LLM ermittelt Field-Selectors aus den HTML-Snippets
        3. Regelbasierte Extraktion aller Einträge
        
        Args:
            url: Die URL der Webseite
            template: Name des Templates
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            context: Optionaler Kontext für die Transformation
            additional_field_descriptions: Zusätzliche Feldbeschreibungen
            use_cache: Ob der Cache verwendet werden soll
            use_selector_extraction: Ob Selector-Extraktion verwendet werden soll (bei strukturierten Feldern)
            container_selector: CSS-Selector für Event-Container (z.B. "li.single-element")
            
        Returns:
            TransformerResponse: Die Antwort mit dem transformierten Text
        """
        try:
            # Webseiten-Inhalt abrufen
            self.logger.info(f"Rufe Webseiten-Inhalt ab: {url}")
            
            # Headers für bessere Kompatibilität
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Webseite abrufen
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            raw_html: str = response.text

            raw_html = "url: " + url + "\n" + raw_html
            
            # Prüfe ob strukturierte Felder vorhanden sind
            field_descriptions = self.transcriber.extract_field_descriptions(
                template=template,
                template_content=template_content,
                additional_field_descriptions=additional_field_descriptions,
                logger=self.logger
            )
            
            # Wenn strukturierte Felder vorhanden und Selector-Extraktion aktiviert
            if use_selector_extraction and field_descriptions:
                # Container-Selector muss angegeben sein
                if not container_selector:
                    self.logger.warning(
                        "use_selector_extraction=True aber kein container_selector angegeben. "
                        "Fallback zu normaler Transformation."
                    )
                    # Fallback zu normaler Transformation
                else:
                    try:
                        self.logger.info("Verwende zweistufigen Ansatz: Selector-Extraktion + regelbasierte Scraping")
                        self.logger.info(f"Verwende Container-Selector: {container_selector}")
                        
                        # Stufe 1: HTML-Snippets mit gegebenem Selector extrahieren
                        html_snippets = self._extract_snippets_with_selector(
                            html=raw_html,
                            container_selector=container_selector,
                            max_snippets=50
                        )
                        
                        if not html_snippets:
                            self.logger.warning(
                                f"Keine Container mit Selector '{container_selector}' gefunden, "
                                "fallback zu normaler Transformation"
                            )
                            # Fallback zu normaler Transformation
                        else:
                            # Stufe 2: Field-Selectors mit LLM ermitteln
                            self.logger.info(f"Ermittle Field-Selectors für {len(field_descriptions)} Felder...")
                            selectors = self._extract_selectors_with_llm(
                                html_snippets=html_snippets,
                                field_descriptions=field_descriptions,
                                source_language=source_language,
                                use_cache=use_cache,
                                container_selector=container_selector
                            )
                            
                            # Stufe 3: Alle Einträge extrahieren - verwende ROHES HTML
                            self.logger.info("Extrahiere alle Einträge mit Selectors...")
                            extracted_data = self._scrape_with_selectors(
                                html=raw_html,
                                selectors=selectors,
                                source_url=url
                            )
                            
                            self.logger.info(f"Extrahiert: {len(extracted_data)} Einträge")
                            
                            # Direkt die Liste zurückgeben - Template wurde nur für Feldbeschreibungen verwendet
                            from src.core.models.transformer import TransformerData
                            transformer_data = TransformerData(
                                text=json.dumps(extracted_data, ensure_ascii=False, indent=2),  # JSON-String für Kompatibilität
                                language=source_language,
                                format=OutputFormat.JSON,
                                structured_data={
                                    "selectors": selectors,
                                    "items": extracted_data,  # Liste direkt zurückgeben
                                    "item_count": len(extracted_data)
                                }
                            )
                            
                            return self.create_response(
                                processor_name="transformer",
                                result=transformer_data,
                                request_info={
                                    "url": url,
                                    "field_count": len(field_descriptions),
                                    "extracted_count": len(extracted_data),
                                    "method": "selector_extraction",
                                    "container_selector": container_selector
                                },
                                response_class=TransformerResponse,
                                from_cache=False,
                                cache_key=""
                            )
                    except Exception as e:
                        # Fallback: Normale Template-Transformation bei Fehlern
                        self.logger.warning(f"Selector-Extraktion fehlgeschlagen, verwende normale Transformation: {str(e)}")
                        # Weiter mit normaler Transformation
            
            # Fallback: Normale Template-Transformation
            # Hier verwenden wir bereinigtes HTML, um Token zu sparen
            self.logger.info("Verwende normale Template-Transformation")
            return self.transformByTemplate(
                text=raw_html,
                template=template,
                template_content=template_content,
                source_language=source_language,
                target_language=target_language,
                context=context,
                additional_field_descriptions=additional_field_descriptions,
                use_cache=use_cache
            )
            
        except requests.RequestException as e:
            self.logger.error(f"Fehler beim Abrufen der Webseite: {str(e)}")
            
            error_info = ErrorInfo(
                code="URL_FETCH_ERROR",
                message=f"Fehler beim Abrufen der Webseite: {str(e)}",
                details={
                    "error_type": type(e).__name__,
                    "url": url,
                    "traceback": traceback.format_exc()
                }
            )
            
            return self.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    "url": url,
                    "template": template,
                    "source_language": source_language,
                    "target_language": target_language
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )
        except Exception as e:
            self.logger.error(f"Fehler bei der URL-Transformation: {str(e)}")
            
            error_info = ErrorInfo(
                code="URL_TRANSFORMATION_ERROR",
                message=f"Fehler bei der URL-Transformation: {str(e)}",
                details={
                    "error_type": type(e).__name__,
                    "url": url,
                    "template": template,
                    "traceback": traceback.format_exc()
                }
            )
            
            return self.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    "url": url,
                    "template": template,
                    "source_language": source_language,
                    "target_language": target_language
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

    def transformByTemplate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        template: Optional[str] = None,
        template_content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        model: Optional[str] = None,
        provider: Optional[str] = None
    ) -> TransformerResponse:
        """Transformiert Text nach einem Template."""
        try:
            # Template-Transformation durchführen
            result: TransformationResult = self.transcriber.transform_by_template(
                text=text,
                template=template,
                template_content=template_content,
                target_language=target_language,
                context=context,
                additional_field_descriptions=additional_field_descriptions,
                logger=self.logger,
                use_cache=use_cache,
                model=model,
                provider=provider
            )
            
            # Prüfe, ob ein Fehler zurückgegeben wurde
            if result.structured_data and "error" in result.structured_data:
                # Es handelt sich um eine Fehler-Response vom Transcriber
                error_info = ErrorInfo(
                    code="TEMPLATE_ERROR",
                    message=result.structured_data["error"],  # Spezifische Fehlermeldung aus structured_data
                    details={
                        "error_type": result.structured_data.get("error_type", "TemplateError"),
                        "template": template,
                        **{k: v for k, v in result.structured_data.items() if k not in ["error", "error_type"]}
                    }
                )
                
                # Erstelle Fehler-Response
                return self.create_response(
                    processor_name="transformer",
                    result=None,
                    request_info={
                        "text": text[:100] + "..." if len(text) > 100 else text,
                        "template": template,
                        "template_content": template_content[:100] + "..." if template_content and len(template_content) > 100 else template_content,
                        "source_language": source_language,
                        "target_language": target_language
                    },
                    response_class=TransformerResponse,
                    from_cache=False,
                    cache_key="",
                    error=error_info
                )
            
            # Erstelle TransformerData aus dem Ergebnis
            transformer_data = TransformerData(
                text=result.text,
                language=target_language,
                format=OutputFormat.TEXT,
                summarized=False,
                structured_data=result.structured_data
            )
            
            # Erstelle Response
            return self.create_response(
                processor_name="transformer",
                result=transformer_data,
                request_info={
                    "text": text[:100] + "..." if len(text) > 100 else text,
                    "template": template,
                    "template_content": template_content[:100] + "..." if template_content and len(template_content) > 100 else template_content,
                    "source_language": source_language,
                    "target_language": target_language,
                    "context": context,
                    "additional_field_descriptions": additional_field_descriptions,
                    "use_cache": use_cache
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=""
            )
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            
            # Erstelle Fehler-Response mit korrektem ErrorInfo-Objekt
            error_info = ErrorInfo(
                code="TEMPLATE_TRANSFORMATION_ERROR",
                message=f"Fehler bei der Template-Transformation: {str(e)}",
                details={
                    "error_type": type(e).__name__,
                    "template": template,
                    "traceback": traceback.format_exc()
                }
            )
            
            return self.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    "text": text[:100] + "..." if len(text) > 100 else text,
                    "template": template,
                    "template_content": template_content[:100] + "..." if template_content and len(template_content) > 100 else template_content,
                    "source_language": source_language,
                    "target_language": target_language
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

    def _extract_link_info(self, link: PageElement | Tag, source_url: str) -> Dict[str, str]:
        """Extrahiert Name und URL aus einem Link-Tag."""
        if not isinstance(link, Tag):
            return {"Name": str(link.get_text(strip=True)) if hasattr(link, 'get_text') else ""}
            
        href_attr = link.get('href')
        href: str = str(href_attr) if href_attr is not None else ''
        if href:
            return {
                "Name": str(link.get_text(strip=True)),
                "Url": urljoin(source_url, href)
            }
        return {"Name": str(link.get_text(strip=True))}

    def _process_cell_content(self, cell: Tag, source_url: str) -> Any:
        """Verarbeitet den Inhalt einer Tabellenzelle."""
        links = cell.find_all('a')
        if not links:
            return str(cell.get_text(strip=True))
            
        if len(links) == 1:
            return self._extract_link_info(links[0], source_url)
            
        link_objects = [
            self._extract_link_info(link, source_url) 
            for link in links
        ]
        return link_objects if link_objects else str(cell.get_text(strip=True))

    def transformHtmlTable(
        self,
        source_url: str,
        output_format: str = "json",
        table_index: Optional[int] = None,
        start_row: Optional[int] = None,
        row_count: Optional[int] = None
    ) -> TransformerResponse:
        """
        Transformiert HTML-Tabellen von einer Webseite in JSON Format.
        
        Args:
            source_url: Die URL der Webseite mit der Tabelle
            output_format: Das gewünschte Ausgabeformat (default: "json")
            table_index: Optional - Index der gewünschten Tabelle (0-basiert). 
                        Wenn None, werden alle Tabellen zurückgegeben.
            start_row: Optional - Startzeile für das Paging (0-basiert)
            row_count: Optional - Anzahl der zurückzugebenden Zeilen
            
        Returns:
            TransformerResponse: Das Transformationsergebnis
        """
        # Response initialisieren
        response = TransformerResponse(
            data=TransformerData(
                text=source_url,
                language="html",
                format=OutputFormat.HTML
            )
        )
        
        try:
            # Validiere Eingaben
            if not source_url.strip():
                raise ValueError("source_url darf nicht leer sein")
            
            if output_format.lower() != "json":
                raise ValueError("Aktuell wird nur JSON als output_format unterstützt")

            if table_index is not None and table_index < 0:
                raise ValueError("table_index muss größer oder gleich 0 sein")

            if start_row is not None and start_row < 0:
                raise ValueError("start_row muss größer oder gleich 0 sein")

            if row_count is not None:
                if row_count < 0:
                    raise ValueError("row_count muss größer oder gleich 0 sein")
                if row_count == 0:
                    row_count = None

            self.logger.info("Starte HTML-Tabellen Transformation")
            
            # Verwende requests für das Abrufen der Webseite
            import requests
            
            # Hole die Webseite
            try:
                request_headers: Dict[str, str] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                page = requests.get(source_url, headers=request_headers, timeout=10)
                page.raise_for_status()  # Wirft HTTPError für 4XX/5XX Status
                source_html = page.text
            except requests.RequestException as e:
                raise ProcessingError(f"Fehler beim Abrufen der Webseite: {str(e)}")
            
            soup = BS(source_html, 'html.parser')
            tables = soup.find_all('table')
            
            if not tables:
                raise ValueError("Keine HTML-Tabelle auf der Webseite gefunden")

            if table_index is not None and table_index >= len(tables):
                raise ValueError(f"table_index {table_index} ist zu groß. Es wurden nur {len(tables)} Tabellen gefunden.")
            
            all_tables: List[Dict[str, Any]] = []
            tables_to_process = [tables[table_index]] if table_index is not None else tables
            
            for idx, table in enumerate(tables_to_process):
                # Headers extrahieren
                headers = [
                    th.get_text(strip=True) 
                    for th in table.find_all('th')
                ]
                
                # Wenn keine Headers gefunden wurden, erste Zeile als Header verwenden
                if not headers:
                    first_row = table.find('tr')
                    if first_row:
                        headers: List[str] = [
                            td.get_text(strip=True) 
                            for td in first_row.find_all('td')
                        ]
                
                rows: List[Dict[str, Any]] = []
                current_group_info: Dict[str, str] = {}
                
                # Zeilen verarbeiten
                for tr in table.find_all('tr')[1 if headers else 0:]:
                    cells = tr.find_all('td')
                    if not cells:
                        continue
                        
                    # Gruppierungsinfo verarbeiten
                    first_cell = cells[0]
                    if len(cells) == 1:
                        if first_cell.get('colspan'):
                            links = first_cell.find_all('a')
                            if links and len(links) == 1:
                                current_group_info = self._extract_link_info(links[0], source_url)
                            else:
                                current_group_info = {"Name": first_cell.get_text(strip=True)}
                            continue
                    
                    # Normale Zeile verarbeiten
                    row = {
                        headers[i]: self._process_cell_content(cell, source_url)
                        for i, cell in enumerate(cells)
                        if i < len(headers)
                    }
                    
                    if row and any(row.values()):
                        if current_group_info:
                            row['group'] = current_group_info
                        rows.append(row)

                # Paging anwenden
                total_rows: int = len(rows)
                start_idx: int = start_row if start_row is not None else 0
                
                if row_count is None:
                    end_idx = total_rows
                else:
                    end_idx = min(start_idx + row_count, total_rows)
                
                rows = rows[start_idx:end_idx]

                # Tabellendaten sammeln
                table_data: Dict[str, Any] = {
                    "table_index": table_index if table_index is not None else idx,
                    "headers": list(headers) + ["group"] if current_group_info else list(headers),
                    "rows": rows,
                    "metadata": {
                        "total_rows": total_rows,
                        "column_count": len(headers),
                        "has_group_info": bool(current_group_info),
                        "paging": {
                            "start_row": start_row if start_row is not None else 0,
                            "row_count": len(rows),
                            "has_more": end_idx < total_rows
                        }
                    }
                }
                all_tables.append(table_data)
            
            # Gesamtergebnis erstellen
            result: Dict[str, str | int | List[Dict[str, Any]]] = {
                "url": source_url,
                "table_count": len(all_tables),
                "tables": all_tables
            }
 
            # Erstelle TransformerData aus dem Ergebnis
            transformer_data = TransformerData(
                text="",
                language="json",
                format=OutputFormat.JSON,
                summarized=False,
                structured_data=result
            )
            
            # Antwort erstellen mit der BaseProcessor-Methode
            return self.create_response(
                processor_name="transformer",
                result=transformer_data,
                request_info={
                    "source_url": source_url,
                    "table_index": table_index,
                    "start_row": start_row,
                    "row_count": row_count,
                    "output_format": output_format
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=""
            )

        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            self.logger.error(f"Fehler bei der HTML-Tabellen Transformation: {str(e)}")
            
            # Erstelle Response mit self.create_response statt TransformerResponse.create
            response = self.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    "source_url": source_url,
                    "table_index": table_index,
                    "start_row": start_row,
                    "row_count": row_count,
                    "output_format": output_format
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

            return response


    def get_template_processor(self) -> WhisperTranscriber:
        """Gibt den Template-Prozessor zurück."""
        return self.transcriber 