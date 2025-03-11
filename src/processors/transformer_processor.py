"""
Transformer processor module.
Handles text transformation using LLM models.

LLM-Tracking Logik:
-----------------
Der Prozessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
   - Pro Operation (Übersetzung, Zusammenfassung, etc.)
   - Mit Details wie Model, Zweck, Tokens, Dauer
   - Zeitstempel für Nachverfolgbarkeit

Ablauf:
1. LLMInfo wird für den Gesamtprozess initialisiert
2. Jede LLM-Operation (translate, summarize, etc.) erstellt LLMRequests
3. Diese werden zum LLMInfo hinzugefügt und aggregiert
4. Die Response enthält beide Informationsebenen

Beispiel Response:
{
  "llm_info": {
    "requests_count": 3,
    "total_tokens": 1500,
    "total_duration": 2500,
    "total_cost": 0.15,
    "requests": [
      {
        "model": "gpt-4",
        "purpose": "translation",
        "tokens": 500,
        "duration": 800,
        "timestamp": "2024-01-20T10:15:30Z"
      },
      {
        "model": "gpt-4", 
        "purpose": "summarization",
        "tokens": 400,
        "duration": 700,
        "timestamp": "2024-01-20T10:15:31Z"
      }
    ]
  }
}
"""

import hashlib
from typing import Dict, Any, Optional, List
from datetime import datetime
import traceback
import uuid
from urllib.parse import urljoin

from bs4 import BeautifulSoup as BS, ResultSet  # Umbenennung um Namenskonflikte zu vermeiden
from bs4.element import NavigableString, Tag, PageElement
from openai import OpenAI

from src.core.models.transformer import TranslationResult, TransformationResult
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.llm import LLMInfo
from src.core.models.base import RequestInfo, ProcessInfo, ErrorInfo
from src.core.models.transformer import (
    TransformerResponse, TransformerInput, TransformerOutput, 
    TransformerData
)
from src.core.models.enums import ProcessorType, OutputFormat, ProcessingStatus
from src.core.config_keys import ConfigKeys
from src.core.models.response_factory import ResponseFactory
from .cacheable_processor import CacheableProcessor

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
    
    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration laden
            transformer_config = self.load_processor_config('transformer')
            
            # Konfigurationswerte laden
            self.model: str = transformer_config.get('model', 'gpt-4')
            self.target_format: OutputFormat = transformer_config.get('target_format', OutputFormat.TEXT)
            
            # Das temp_dir wird jetzt vollständig vom BaseProcessor verwaltet
            # und basiert auf der Konfiguration in config.yaml
            
            # OpenAI Client initialisieren
            config_keys = ConfigKeys()
            self.client = OpenAI(api_key=config_keys.openai_api_key)
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            # Übergebe den Prozessornamen und die Cache-Verzeichnisstruktur für konsistente Verwendung
            transformer_config.update({
                'processor_name': 'transformer',
                'cache_dir': str(self.cache_dir),  # Haupt-Cache-Verzeichnis
                'temp_dir': str(self.temp_dir),    # Temporäres Unterverzeichnis
                'debug_dir': str(self.temp_dir / "debug")  # Debug-Verzeichnis im temp-Bereich
            })
            self.transcriber = WhisperTranscriber(transformer_config)
            
            self.logger.debug("Transformer Processor initialisiert",
                            model=self.model,
                            target_format=self.target_format)
                            
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
        # TransformationResult aus Cache-Daten erstellen
        # LLM-Informationen werden bewusst weggelassen, da sie bei Cache-Treffern nicht vorhanden sind
        return TransformationResult.from_cache(cached_data)
    
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
        Transformiert einen Text.
        
        Args:
            source_text: Der zu transformierende Text
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Das Zielformat
            context: Optionaler Kontext für die Transformation
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            TransformerResponse: Die Response mit dem transformierten Text
        """
        # Cache-Schlüssel generieren
        cache_key = None
        if use_cache and self.is_cache_enabled():
            cache_key = self._create_cache_key(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize
            )
            
            # Prüfen, ob im Cache vorhanden
            cache_hit, cached_result = self.get_from_cache(cache_key)
            
            if cache_hit and cached_result:
                self.logger.info(f"Cache-Hit für Transformation: {cache_key[:8]}...")
                
                # Response aus dem Cache erstellen
                return self._create_response_from_cached_result(
                    cached_result=cached_result,
                    source_text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    summarize=summarize,
                    target_format=target_format
                )
        
        # Initialisiere format_to_use am Anfang
        format_to_use: OutputFormat = target_format or self.target_format
         
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            context = self.validate_context(context)

            llm_info = LLMInfo(model=self.model, purpose="transform-text")

            self.logger.info(f"Starte Transformation: {source_language} -> {target_language}")
                 
            # Führe Übersetzung durch
            result_text = source_text
            if source_language != target_language:
                translation_result: TranslationResult = self.transcriber.translate_text(
                    text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = translation_result.text
                if translation_result.requests:
                    llm_info.add_request(translation_result.requests)
             
            # Führe Zusammenfassung durch
            if summarize:
                summary_result: TransformationResult = self.transcriber.summarize_text(
                    text=result_text,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = summary_result.text
                if summary_result.requests:
                    llm_info.add_request(summary_result.requests)

            # Formatierung anwenden
            if format_to_use != OutputFormat.TEXT:
                format_result: TransformationResult = self.transcriber.format_text(
                    text=result_text,
                    format=format_to_use,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = format_result.text
                if format_result.requests:
                    llm_info.add_request(format_result.requests)

            # Debug Output
            self.transcriber.saveDebugOutput(
                text=result_text,
                context=context,
                logger=self.logger
            )
            
            # Erstelle das finale TransformationResult
            result = TransformationResult(
                text=result_text,
                target_language=target_language,
                requests=[], # Alle Requests sind bereits im llm_info-Objekt aggregiert
                llm_info=llm_info
            )
            
            # Speichere im Cache, wenn aktiviert
            if use_cache and self.is_cache_enabled() and cache_key:
                self.save_to_cache(cache_key, result)

            # Response erstellen mit ResponseFactory
            return ResponseFactory.create_response(
                processor_name=ProcessorType.TRANSFORMER.value,
                result=TransformerData(
                    input=TransformerInput(
                        text=source_text,
                        language=source_language,
                        format=format_to_use,
                        summarize=summarize
                    ),
                    output=TransformerOutput(
                        text=result_text,
                        language=target_language,
                        format=format_to_use,
                        summarized=summarize
                    )
                ),
                request_info={
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': format_to_use.value
                },
                response_class=TransformerResponse,
                llm_info=llm_info
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
            self.logger.error(f"Fehler bei der Transformation: {str(e)}")
         
            # Error-Response mit ResponseFactory
            return ResponseFactory.create_response(
                processor_name=ProcessorType.TRANSFORMER.value,
                result=TransformerData(
                    input=TransformerInput(
                        text=source_text,
                        language=source_language,
                        format=format_to_use,
                        summarize=summarize
                    ),
                    output=TransformerOutput(
                        text="",
                        language=target_language,
                        format=format_to_use,
                        summarized=False
                    )
                ),
                request_info={
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': format_to_use.value
                },
                response_class=TransformerResponse,
                error=error_info
            )
    
    def _create_response_from_cached_result(self,
                                           cached_result: TransformationResult,
                                           source_text: str,
                                           source_language: str,
                                           target_language: str,
                                           summarize: bool = False,
                                           target_format: Optional[OutputFormat] = None) -> TransformerResponse:
        """
        Erstellt eine Response aus einem gecachten Transformationsergebnis.
        
        Args:
            cached_result: Das TransformationResult aus dem Cache
            source_text: Der ursprüngliche Text
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            summarize: Ob der Text zusammengefasst wurde
            target_format: Das Zielformat
            
        Returns:
            TransformerResponse: Die Response mit dem transformierten Text
        """
        format_to_use: OutputFormat = target_format or self.target_format
        
        # Response erstellen mit ResponseFactory
        return ResponseFactory.create_response(
            processor_name=ProcessorType.TRANSFORMER.value,
            result=TransformerData(
                input=TransformerInput(
                    text=source_text,
                    language=source_language,
                    format=format_to_use,
                    summarize=summarize
                ),
                output=TransformerOutput(
                    text=cached_result.text,
                    language=target_language,
                    format=format_to_use,
                    summarized=summarize,
                    structured_data=cached_result.structured_data
                )
            ),
            request_info={
                'source_language': source_language,
                'target_language': target_language,
                'summarize': summarize,
                'target_format': format_to_use.value,
                'from_cache': True
            },
            response_class=TransformerResponse
        )

    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None,
        use_cache: bool = True
    ) -> TransformerResponse:
        """
        Transformiert Text basierend auf einem vordefinierten Markdown-Template.
        Die Templates befinden sich im ./templates-Ordner und enthalten Anweisungen in geschweiften Klammern
        für strukturierte Ausgaben vom LLM Modell.

        Args:
            source_text (str): Der zu transformierende Text
            source_language (str): Sprachcode (ISO 639-1) für die Quellsprache
            target_language (str): Sprachcode (ISO 639-1) für die Zielsprache
            context (Dict[str, Any], optional): Dictionary mit Kontext-Informationen für Template-Variablen
            template (str, optional): Name des Templates (ohne .md Endung)
            use_cache (bool, optional): Ob der Cache verwendet werden soll, standardmäßig True

        Returns:
            TransformerResponse: Das validierte Transformationsergebnis mit Prozess-Informationen
        """
        # Cache-Schlüssel generieren und Cache prüfen
        cache_key = None
        if use_cache and self.is_cache_enabled() and template:
            cache_key = self._create_cache_key(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                template=template
            )
            
            # Prüfen, ob im Cache vorhanden
            cache_hit, cached_result = self.get_from_cache(cache_key)
            
            if cache_hit and cached_result:
                self.logger.info(f"Cache-Hit für Template-Transformation: {cache_key[:8]}...")
                
                # Response aus dem Cache erstellen
                return self._create_response_from_cached_result(
                    cached_result=cached_result,
                    source_text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    target_format=self.target_format
                )
        
        # Response initialisieren
        response = TransformerResponse(
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_language": source_language,
                    "target_language": target_language,
                    "template": template,
                    "context": context
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor=str(ProcessorType.TRANSFORMER.value),
                started=datetime.now().isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=source_text,
                    language=source_language,
                    format=self.target_format,
                    translated_text=None,
                    summarize=False
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language=target_language,
                    format=self.target_format,
                    summarized=False
                )
            )
        )
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            if template is not None:
                template = self.validate_text(template, "template")
            validated_context: Dict[str, Any] | None = self.validate_context(context)

            llm_info = LLMInfo(model=self.model, purpose="transform-text-by-template")

            self.logger.info(f"Starte Template-Transformation: {source_language} -> {target_language}")
            
            # Zuerst den Quelltext übersetzen
            result_text:str = source_text
            if source_language != target_language:
                self.logger.info("Übersetze Quelltext")
                    
                translation_result: TranslationResult = self.transcriber.translate_text(
                    text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = translation_result.text

                if translation_result.requests and len(translation_result.requests) > 0:
                    llm_info.add_request(translation_result.requests)

                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=TransformerInput(
                            text=source_text,
                            language=source_language,
                            format=self.target_format,
                            translated_text=result_text,
                            summarize=False
                        ),
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=self.target_format,
                            summarized=False
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Template-Transformation durchführen
            has_transformed_content = False
            transformed_content_data = None
            if template is not None:
                self.logger.info("Führe Template-Transformation durch")

                    # Template-Transformation durchführen
                transformed_content: TransformationResult = self.transcriber.transform_by_template(
                    text=result_text,
                    target_language=target_language,
                    template=template,
                    context=context,
                    logger=self.logger
                )
                result_text = transformed_content.text
                transformed_content_data = getattr(transformed_content, 'structured_data', None)
                has_transformed_content = True
                if transformed_content.requests and len(transformed_content.requests) > 0:
                    llm_info.add_request(transformed_content.requests)

                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=OutputFormat.MARKDOWN,
                            summarized=False,
                            structured_data=transformed_content_data
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Debug Output
            self.transcriber.saveDebugOutput(
                text=result_text,
                context=validated_context,
                logger=self.logger
            )

            # Final transformiertes Ergebnis erstellen
            # Strukturierte Daten nur bei Template-Transformation
            final_result = TransformationResult(
                text=result_text,
                target_language=target_language,
                structured_data=transformed_content_data if has_transformed_content else None,
                requests=[],  # Alle Requests sind bereits im llm_info-Objekt aggregiert
                llm_info=llm_info
            )
            
            # Speichere im Cache, wenn aktiviert
            if use_cache and self.is_cache_enabled() and cache_key:
                self.save_to_cache(cache_key, final_result)
            
            return response

        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            
            return ResponseFactory.create_response(
                processor_name=response.process.main_processor,
                result=response.data,
                request_info=response.request.parameters,
                response_class=TransformerResponse,
                llm_info=None,
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
            
        if len(links) == 1 and isinstance(links[0], Tag):
            return self._extract_link_info(links[0], source_url)
            
        link_objects = [
            self._extract_link_info(link, source_url) 
            for link in links 
            if isinstance(link, Tag)
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
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_url": source_url,
                    "output_format": output_format,
                    "table_index": table_index,
                    "start_row": start_row,
                    "row_count": row_count
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor=str(ProcessorType.TRANSFORMER.value),
                started=datetime.now().isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=source_url,
                    language="html",
                    format=OutputFormat.HTML
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language="json",
                    format=OutputFormat.JSON
                )
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

            llm_info = LLMInfo(model=self.model, purpose="transform-html-table")
            
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
                if not isinstance(table, Tag):
                    continue
                    
                # Headers extrahieren
                headers = [
                    th.get_text(strip=True) 
                    for th in table.find_all('th') 
                    if isinstance(th, Tag)
                ]
                
                # Wenn keine Headers gefunden wurden, erste Zeile als Header verwenden
                if not headers:
                    first_row: PageElement | Tag | NavigableString | None = table.find('tr')
                    if first_row and isinstance(first_row, Tag):
                        headers: List[str] = [
                            td.get_text(strip=True) 
                            for td in first_row.find_all('td') 
                            if isinstance(td, Tag)
                        ]
                
                rows: List[Dict[str, Any]] = []
                current_group_info: Dict[str, str] = {}
                
                # Zeilen verarbeiten
                for tr in table.find_all('tr')[1 if headers else 0:]:
                    if not isinstance(tr, Tag):
                        continue
                        
                    cells: ResultSet[PageElement | Tag | NavigableString] = tr.find_all('td')
                    if not cells:
                        continue
                        
                    # Gruppierungsinfo verarbeiten
                    first_cell = cells[0]
                    if len(cells) == 1 and isinstance(first_cell, Tag):
                        if first_cell.get('colspan'):
                            links: ResultSet[PageElement | Tag | NavigableString] = first_cell.find_all('a')
                            if links and len(links) == 1 and isinstance(links[0], Tag):
                                current_group_info: Dict[str, str] = self._extract_link_info(links[0], source_url)
                            else:
                                current_group_info = {"Name": first_cell.get_text(strip=True)}
                            continue
                    
                    # Normale Zeile verarbeiten
                    row = {
                        headers[i]: self._process_cell_content(cell, source_url)
                        for i, cell in enumerate(cells)
                        if i < len(headers) and isinstance(cell, Tag)
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
                table_data: Dict[str, int | List[str] | List[Dict[str, Any]] | Dict[str, int | Dict[str, int | bool]]] = {
                    "table_index": table_index if table_index is not None else idx,
                    "headers": list(headers) + ["group"] if current_group_info else list(headers),
                    "rows": rows,
                    "metadata": {
                        "total_rows": total_rows,
                        "visible_rows": len(rows),
                        "column_count": len(headers) + (1 if current_group_info else 0),
                        "paging": {
                            "start_row": start_idx,
                            "row_count": row_count if row_count is not None else total_rows,
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
            
            # Response vervollständigen
            response = TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=TransformerData(
                    input=response.data.input,
                    output=TransformerOutput(
                        text="",
                        language="json",
                        format=OutputFormat.JSON,
                        structured_data=result
                    )
                ),
                llm_info=llm_info,
                status=ProcessingStatus.SUCCESS,
                error=None
            )
            return response

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
            
            return ResponseFactory.create_response(
                processor_name=response.process.main_processor,
                result=response.data,
                request_info=response.request.parameters,
                response_class=TransformerResponse,
                llm_info=None,
                error=error_info
            ) 