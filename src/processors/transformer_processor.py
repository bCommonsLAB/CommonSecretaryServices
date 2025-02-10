"""
Transformer processor module.
Handles text transformation using LLM models.
"""
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, cast
from datetime import datetime
import traceback
import uuid
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import ResultSet, Tag, NavigableString, PageElement
from openai import OpenAI

from src.core.models.transformer import TranslationResult, TransformationResult
from src.core.exceptions import ProcessingError
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.llm import LLMInfo
from src.core.models.base import RequestInfo, ProcessInfo, ErrorInfo
from src.core.models.transformer import (
    TransformerResponse, TransformerInput, TransformerOutput, 
    TransformerData
)
from src.core.models.enums import ProcessorType, OutputFormat, ProcessingStatus
from src.core.config_keys import ConfigKeys
from utils.transcription_utils import TransformationResult
from .base_processor import BaseProcessor

class TransformerProcessor(BaseProcessor):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    """
    
    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        self.logger: Optional[ProcessingLogger] = None
        
        try:
            # Konfiguration laden
            transformer_config = self.load_processor_config('transformer')
            
            # Logger initialisieren
            self.logger = self.init_logger("TransformerProcessor")
            
            # Konfigurationswerte laden
            self.model: str = transformer_config.get('model', 'gpt-4')
            self.target_format: OutputFormat = transformer_config.get('target_format', OutputFormat.TEXT)
            
            # Temporäres Verzeichnis einrichten
            self.init_temp_dir("transformer", transformer_config)
            
            # OpenAI Client initialisieren
            config_keys = ConfigKeys()
            self.client = OpenAI(api_key=config_keys.openai_api_key)
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            self.transcriber = WhisperTranscriber(transformer_config)
            
            if self.logger:
                self.logger.debug("Transformer Processor initialisiert",
                                model=self.model,
                                target_format=self.target_format,
                                temp_dir=str(self.temp_dir))
                            
        except Exception as e:
            if self.logger:
                self.logger.error("Fehler bei der Initialisierung des TransformerProcessors",
                                error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def transform(
        self, 
        source_text: str, 
        source_language: str, 
        target_language: str, 
        summarize: bool = False, 
        target_format: Optional[OutputFormat] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> TransformerResponse:
        """
        Führt Übersetzung und optional Zusammenfassung durch.
        
        Args:
            source_text: Der zu transformierende Text
            source_language: Sprachcode der Quellsprache
            target_language: Sprachcode der Zielsprache
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Optional, das Zielformat
            context: Optional, zusätzliche Kontextinformationen
            
        Returns:
            TransformerResponse: Das Transformationsergebnis
        """
        
        # Response initialisieren
        response = TransformerResponse(
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize,
                    "target_format": target_format or self.target_format
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
                    format=target_format or self.target_format,
                    summarize=summarize
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language=target_language,
                    format=target_format or self.target_format,
                    summarized=summarize
                )
            )
        )
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            format_to_use = target_format or self.target_format
            context = self.validate_context(context)

            llm_info = LLMInfo(model=self.model, purpose="transform-text")

            # Debug-Verzeichnis
            debug_dir = Path('./temp-processing/transform')
            if context and 'uploader' in context:
                debug_dir = Path(f'{debug_dir}/{context["uploader"]}')
            debug_dir.mkdir(parents=True, exist_ok=True)

            if self.logger:
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
                if translation_result.requests and len(translation_result.requests) > 0:
                    llm_info.add_request(translation_result.requests)
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=summarize
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Führe Zusammenfassung durch
            if summarize:
                summary_result: TransformationResult = self.transcriber.summarize_text(
                    text=result_text,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text: str = summary_result.text
                if summary_result.requests and len(summary_result.requests) > 0:
                    llm_info.add_request(summary_result.requests)
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=True
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Formatierung anwenden
            if format_to_use != OutputFormat.TEXT:
                format_result: TransformationResult = self.transcriber.format_text(
                    text=result_text,
                    format=format_to_use,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text: str = format_result.text
                if format_result.requests and len(format_result.requests) > 0:
                    llm_info.add_request(format_result.requests)
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=response.data.output.summarized
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Debug Output
            self.transcriber.saveDebugOutput(
                text=result_text,
                context=context,
                logger=self.logger
            )

            # Response vervollständigen
            response = TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
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
            if self.logger:
                self.logger.error(f"Fehler bei der Transformation: {str(e)}")
            
            return TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                status=ProcessingStatus.ERROR,
                error=error_info
            )

    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None
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

        Returns:
            TransformerResponse: Das validierte Transformationsergebnis mit Prozess-Informationen
        """
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

            if self.logger:
                self.logger.info(f"Starte Template-Transformation: {source_language} -> {target_language}")
                
                if validated_context:
                    self.logger.debug("Context-Informationen", context=validated_context)

            # Zuerst den Quelltext übersetzen
            result_text:str = source_text
            if source_language != target_language:
                if self.logger:
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
                        input=response.data.input,
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
            if template is not None:
                if self.logger:
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
                            structured_data=transformed_content.structured_data
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

            # Response vervollständigen
            response = TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
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
            if self.logger:
                self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            
            return TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                status=ProcessingStatus.ERROR,
                error=error_info
            )

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

            if row_count is not None and row_count < 0:
                raise ValueError("row_count muss größer oder gleich 0 sein")

            llm_info = LLMInfo(model=self.model, purpose="transform-html-table")
            
            if self.logger:
                self.logger.info("Starte HTML-Tabellen Transformation")
            
            # Verwende requests für das Abrufen der Webseite
            import requests
            from bs4 import BeautifulSoup
            import json
            
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
            
            soup = BeautifulSoup(source_html, 'html.parser')
            tables = soup.find_all('table')
            
            if not tables:
                raise ValueError("Keine HTML-Tabelle auf der Webseite gefunden")

            if table_index is not None and table_index >= len(tables):
                raise ValueError(f"table_index {table_index} ist zu groß. Es wurden nur {len(tables)} Tabellen gefunden.")
            
            # Extrahiere Daten aus allen gefundenen Tabellen oder nur der spezifizierten
            all_tables: List[Dict[str, Any]] = []
            tables_to_process: List[PageElement | Tag | NavigableString] | ResultSet[PageElement | Tag | NavigableString] = [tables[table_index]] if table_index is not None else tables
            
            for idx, table in enumerate(tables_to_process):
                headers: List[str] = []
                rows: List[Dict[str, Any]] = []
                current_group_info: Optional[Dict[str, str]] = None
                
                # Headers extrahieren
                for th in table.find_all('th'):
                    headers.append(th.text.strip())
                
                # Wenn keine Headers gefunden wurden, erste Zeile als Header verwenden
                if not headers:
                    first_row = table.find('tr')
                    if first_row:
                        headers = [td.text.strip() for td in first_row.find_all('td')]
                
                # Zeilen extrahieren
                for tr in table.find_all('tr')[1 if headers else 0:]:
                    cells = tr.find_all('td')
                    
                    # Prüfe auf colspan Zeile (Gruppierungsinfo)
                    if cells and len(cells) == 1 and cells[0].get('colspan'):
                        current_group_info = {'group': cells[0].text.strip()}
                    elif len(cells) > 0:  # Nur verarbeiten wenn Zellen vorhanden
                        # Normale Datenzeile
                        row: Dict[str, Any] = {}
                        
                        # Füge Zelleninhalte hinzu
                        for i, cell in enumerate(cells):
                            if i < len(headers):
                                # Prüfe auf Links in der Zelle
                                if isinstance(cell, Tag):  # Type-Check für BeautifulSoup Tag
                                    links = cell.find_all('a')
                                    if links and len(links) > 0:
                                        # Wenn mehrere Links vorhanden sind
                                        if len(links) > 1:
                                            link_objects = []
                                            for link in links:
                                                if isinstance(link, Tag):
                                                    href = link.get('href', '')
                                                    if href:  # Nur Links mit href hinzufügen
                                                        # Konvertiere relative URLs in absolute URLs
                                                        absolute_url = urljoin(source_url, href)
                                                        link_objects.append({
                                                            "Name": link.get_text(strip=True),
                                                            "Url": absolute_url
                                                        })
                                            if link_objects:  # Nur wenn gültige Links gefunden wurden
                                                row[headers[i]] = link_objects
                                            else:
                                                row[headers[i]] = cell.get_text(strip=True)
                                        else:
                                            # Einzelner Link (bisheriges Verhalten)
                                            link = links[0]
                                            if isinstance(link, Tag):
                                                href = link.get('href', '')
                                                if href:  # Nur wenn href vorhanden
                                                    # Konvertiere relative URLs in absolute URLs
                                                    absolute_url = urljoin(source_url, href)
                                                    row[headers[i]] = {
                                                        "Name": link.get_text(strip=True),
                                                        "Url": absolute_url
                                                    }
                                                else:
                                                    row[headers[i]] = cell.get_text(strip=True)
                                    else:
                                        # Wenn keine Links, verwende nur den Text
                                        row[headers[i]] = cell.get_text(strip=True)
                                else:
                                    # Fallback für nicht-Tag Elemente
                                    row[headers[i]] = str(cell.string).strip() if cell.string else ''
                        
                        if row:
                            # Füge Gruppeninformation hinzu wenn vorhanden
                            if current_group_info:
                                row['group'] = current_group_info['group']
                            rows.append(row)
                
                # Tabelle zum Gesamtergebnis hinzufügen
                # Zuerst Rows nach Gruppen organisieren
                grouped_rows: Dict[str, Dict[str, Any]] = {}  # Verwende Dict statt List für eindeutige Gruppen
                
                # Verarbeite alle Rows und ordne sie Gruppen zu
                for row in rows:
                    group_name = row.get('group', 'ungrouped')
                    if group_name not in grouped_rows:
                        grouped_rows[group_name] = {
                            "name": group_name if group_name != 'ungrouped' else None,
                            "rows": []
                        }
                    
                    # Entferne group aus row bevor wir sie hinzufügen
                    row_without_group = {k: v for k, v in row.items() if k != 'group'}
                    grouped_rows[group_name]["rows"].append(row_without_group)

                # Konvertiere grouped_rows Dict in eine Liste und filtere leere Gruppen
                groups_list = [
                    group for group in grouped_rows.values()
                    if len(group["rows"]) > 0 and group["name"] is not None  # Nur nicht-leere und benannte Gruppen
                ]

                # Paging auf Row-Ebene über alle Gruppen hinweg
                if start_row is not None or row_count is not None:
                    start_idx = start_row if start_row is not None else 0
                    end_idx = start_idx + (row_count if row_count is not None else float('inf'))
                    
                    # Neue Liste für die paginierten Gruppen
                    paginated_groups = []
                    current_row = 0
                    
                    for group in groups_list:
                        group_size = len(group["rows"])
                        
                        # Prüfe ob diese Gruppe Rows im gewünschten Bereich hat
                        if current_row + group_size > start_idx:
                            # Berechne Start- und End-Index für diese Gruppe
                            group_start = max(0, start_idx - current_row)
                            group_end = min(group_size, end_idx - current_row)
                            
                            if group_start < group_size:
                                paginated_group = {
                                    "name": group["name"],
                                    "rows": group["rows"][group_start:group_end]
                                }
                                if len(paginated_group["rows"]) > 0:
                                    paginated_groups.append(paginated_group)
                        
                        current_row += group_size
                        if current_row >= end_idx:
                            break
                    
                    # Aktualisiere die groups_list mit den paginierten Gruppen
                    groups_list = paginated_groups

                # Gesamtzahl der Rows über alle Gruppen berechnen (vor Paging)
                total_rows_before_paging = sum(len(group["rows"]) for group in grouped_rows.values() if group["name"] is not None)
                total_rows_after_paging = sum(len(group["rows"]) for group in groups_list)

                table_data: Dict[str, Any] = {
                    "table_index": table_index if table_index is not None else idx,
                    "headers": list(headers),  # Explizite Konvertierung zu List[str]
                    "groups": groups_list,
                    "metadata": {
                        "total_rows": total_rows_before_paging,  # Gesamtzahl aller Rows
                        "visible_rows": total_rows_after_paging,  # Anzahl der sichtbaren Rows nach Paging
                        "total_groups": len([g for g in grouped_rows.values() if g["name"] is not None]),  # Gesamtzahl aller Gruppen
                        "visible_groups": len(groups_list),  # Anzahl der Gruppen nach Paging
                        "column_count": len(headers),
                        "paging": {
                            "start_row": start_row if start_row is not None else 0,
                            "row_count": row_count if row_count is not None else total_rows_before_paging,
                            "has_more": total_rows_after_paging < total_rows_before_paging
                        }
                    }
                }
                all_tables.append(table_data)
            
            # Gesamtergebnis erstellen
            result = {
                "url": source_url,
                "table_count": len(all_tables),
                "tables": all_tables
            }
            
            # result_json = json.dumps(result, ensure_ascii=False, indent=2)
            
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
            if self.logger:
                self.logger.error(f"Fehler bei der HTML-Tabellen Transformation: {str(e)}")
            
            return TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                status=ProcessingStatus.ERROR,
                error=error_info
            ) 