"""
Event-Processor Modul.
Verarbeitet Event-Informationen und zugehörige Medien.

Funktionalität:
--------------
1. Extrahiert Event-Informationen von der Event-Seite
2. Lädt zugehörige Medien (Videos, Anhänge) herunter
3. Transformiert und speichert alles in einer strukturierten Form
4. Generiert eine Markdown-Datei mit allen Informationen

Ablauf:
-------
1. Validierung der Eingabeparameter
2. Abrufen und Parsen der Event-Seite
3. Download und Verarbeitung der Medien
4. Generierung der Markdown-Datei
5. Finale Übersetzung in Zielsprache
6. Rückgabe der Verarbeitungsergebnisse mit Performance-Metriken
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, TypeVar, Union
from pathlib import Path
import traceback
import time
import requests
from bs4 import BeautifulSoup
import zipfile
import asyncio
import uuid
from contextlib import nullcontext

from src.processors.pdf_processor import PDFResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.video import VideoResponse
from src.core.models.event import (
    EventInput, EventOutput, EventData, EventResponse, BatchEventResponse, BatchEventOutput, BatchEventData, BatchEventInput,
    WebhookConfig, AsyncEventInput, AsyncBatchEventInput
)
from src.core.models.base import (
     ErrorInfo
)
from src.core.models.llm import LLMInfo
from src.core.models.enums import ProcessorType, ProcessingStatus
from src.core.exceptions import ProcessingError
from src.core.models.response_factory import ResponseFactory
from src.processors.video_processor import VideoProcessor
from src.processors.transformer_processor import TransformerProcessor
from .base_processor import BaseProcessor
from src.processors.pdf_processor import PDFProcessor
from src.core.models.notion import NotionBlock, NotionResponse, NotionData, Newsfeed
from src.utils.performance_tracker import get_performance_tracker

# TypeVar für den Rückgabetyp von Tasks definieren
T = TypeVar('T')

class EventProcessor(BaseProcessor):
    """
    Processor für die Verarbeitung von Event-Informationen und zugehörigen Medien.
    """
    
    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den EventProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optional, die Process-ID vom API-Layer
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration laden
            event_config: Dict[str, Any] = self.load_processor_config('event')
            
            # Basis-Verzeichnis für Event-Dateien
            self.base_dir = Path(event_config.get('base_dir', 'events'))
            if not self.base_dir.exists():
                self.base_dir.mkdir(parents=True)
                
            # Das temp_dir wird jetzt vollständig vom BaseProcessor verwaltet
            # und basiert auf der Konfiguration in config.yaml
            
            # Initialisiere Sub-Prozessoren
            self.video_processor = VideoProcessor(resource_calculator, process_id)
            self.transformer_processor = TransformerProcessor(resource_calculator, process_id)
            
            # Semaphore für die Begrenzung gleichzeitiger asynchroner Verarbeitungen
            max_concurrent_tasks = event_config.get('max_concurrent_tasks', 5)
            self._processing_semaphore = asyncio.Semaphore(max_concurrent_tasks)
            
            self.logger.debug("Event Processor initialisiert",
                            base_dir=str(self.base_dir),
                            temp_dir=str(self.temp_dir),
                            max_concurrent_tasks=max_concurrent_tasks)
                            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des EventProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    async def _fetch_event_page(self, url: str) -> str:
        """
        Ruft die Event-Seite ab und extrahiert den HTML-Body.
        
        Args:
            url: URL der Event-Seite
            
        Returns:
            Extrahierter Text der Seite
        """
        start_time = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('fetch_event_page', 'event') if tracker else nullcontext():
                self.logger.info(f"Rufe Event-Seite ab: {url}")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response: requests.Response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extrahiere Text
                text = soup.get_text(separator='\n', strip=True)
                
                self.logger.debug("Event-Seite verarbeitet",
                                processing_time=time.time() - start_time,
                                text_length=len(text))
                
                return text
            
        except Exception as e:
            self.logger.error(f"Fehler beim Abrufen der Event-Seite: {str(e)}")
            raise ProcessingError(f"Fehler beim Abrufen der Event-Seite: {str(e)}")

    async def _process_video(self, video_url: str, source_language: str, target_language: str, use_cache: bool = True) -> Tuple[str, Optional[LLMInfo]]:
        """
        Lädt das Video herunter und extrahiert die Audio-Transkription.
        
        Args:
            video_url: URL zum Video
            source_language: Quellsprache des Videos
            target_language: Zielsprache für die Transkription
            use_cache: Ob die Ergebnisse zwischengespeichert werden sollen
            
        Returns:
            Tuple aus transkribiertem Text und LLM-Info
        """
        start_time: float = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('process_video', 'event') if tracker else nullcontext():
                self.logger.info(f"Verarbeite Video: {video_url}")
                
                # Video in Quellsprache verarbeiten
                result: VideoResponse = await self.video_processor.process(
                    source=video_url,
                    source_language=source_language,
                    target_language=target_language,
                    use_cache=use_cache
                )
                
                if result.error:
                    raise ProcessingError(f"Fehler bei der Video-Verarbeitung: {result.error.message}")
                    
                # Extrahiere Transkription und LLM-Info
                transcription = ""
                if result.data and result.data.transcription:
                    # Extrahiere Text und entferne Zeilenumbrüche
                    raw_text = result.data.transcription.text if hasattr(result.data.transcription, 'text') else ''
                    transcription = ' '.join(raw_text.split())  # Ersetzt alle Whitespaces (inkl. \n) durch einzelne Leerzeichen
                
                self.logger.debug("Video verarbeitet",
                                processing_time=time.time() - start_time,
                                transcription_length=len(transcription))
                
                return transcription, result.process.llm_info
                
        except Exception as e:
            self.logger.error(f"Fehler bei der Video-Verarbeitung: {str(e)}")
            raise ProcessingError(f"Fehler bei der Video-Verarbeitung: {str(e)}")

    async def _generate_markdown(
        self,
        web_text: str,
        video_transcript: str,
        event_data: EventInput,
        target_dir: Path,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[LLMInfo]]:
        """
        Generiert die Markdown-Datei mit allen Informationen.
        
        Args:
            web_text: Extrahierter Text der Event-Seite
            video_transcript: Transkription des Videos
            event_data: Event-Metadaten
            context: Optionaler zusätzlicher Kontext für das Template
            
        Returns:
            Tuple aus generiertem Markdown-Text und LLM-Info
        """
        start_time: float = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('generate_markdown', 'event') if tracker else nullcontext():
                self.logger.info("Generiere Markdown")
                
                # Kontext für Template vorbereiten
                template_context = context or {}
                template_context.update({
                    "event": event_data.event,
                    "session": event_data.session,
                    "track": event_data.track,
                    "day": event_data.day,
                    "starttime": event_data.starttime,
                    "endtime": event_data.endtime,
                    "speakers": event_data.speakers,
                    "url": event_data.url,
                    "video_url": event_data.video_url,
                    "attachments_url": event_data.attachments_url,
                    "web_text": web_text,
                    "video_transcript": video_transcript,
                    # Neue Felder für Video-Formate
                    "video_mp4_url": event_data.video_url.replace('.webm', '.mp4') if event_data.video_url else None
                })
                
                # Template-Transformation in Quellsprache durchführen
                result: TransformerResponse = self.transformer_processor.transformByTemplate(
                    source_text=video_transcript or "Keine Transkription verfügbar.",
                    source_language=event_data.source_language, 
                    target_language=event_data.target_language,  
                    template="Event",
                    context=template_context
                )
                
                if result.error:
                    raise ProcessingError(f"Fehler bei der Markdown-Generierung: {result.error.message}")
                
                # Basis Markdown-Content aus Template
                markdown_content = result.data.output.text
                
                # Anhänge hinzufügen falls vorhanden
                if event_data.attachments_url:
                    markdown_content += "## Presentation\n"
                    markdown_content += f"[Links]({event_data.attachments_url})\n"
                    # Bildergalerie hinzufügen falls vorhanden
                    if context and "gallery" in context and context["gallery"]:
                        markdown_content += "```img-gallery\n"
                        # Vollständiger Pfad: events/[track]/assets
                        gallery_path = str(target_dir / "assets").replace("\\", "/")
                        markdown_content += f"path: {gallery_path}\n"
                        markdown_content += "type: vertical\n"
                        markdown_content += "gutter: 50\n"
                        markdown_content += "sortby: name\n"
                        markdown_content += "sort: asc\n"
                        markdown_content += "columns: 3\n"
                        markdown_content += "```\n"
                
                # Transkription hinzufügen
                markdown_content += "## Transkription\n"
                markdown_content += f"```transcript\n{video_transcript}\n```\n"
                
                self.logger.debug("Markdown generiert",
                                processing_time=time.time() - start_time,
                                markdown_length=len(markdown_content))
                    
                return markdown_content, result.process.llm_info
                
        except Exception as e:
            self.logger.error(f"Fehler bei der Markdown-Generierung: {str(e)}")
            raise ProcessingError(f"Fehler bei der Markdown-Generierung: {str(e)}")

    async def _process_attachments(
        self,
        attachments_url: str,
        event_data: EventInput,
        target_dir: Path
    ) -> Tuple[List[str], str, Optional[LLMInfo]]:
        """
        Verarbeitet die Anhänge eines Events.
        
        Args:
            attachments_url: URL zu den Anhängen
            event_data: Event-Metadaten
            target_dir: Zielverzeichnis für die verarbeiteten Dateien
            
        Returns:
            Tuple aus (Liste der Bildpfade, extrahierter Text, LLM-Info)
            
        Raises:
            ProcessingError: Bei Fehlern in der Verarbeitung
        """
        start_time = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('process_attachments', 'event') if tracker else nullcontext():
                self.logger.info(f"Verarbeite Anhänge: {attachments_url}")
                
                # Erstelle Verzeichnis für Assets
                assets_dir = target_dir / "assets"
                if not assets_dir.exists():
                    assets_dir.mkdir(parents=True)
                    
                # Initialisiere PDF-Processor
                pdf_processor = PDFProcessor(self.resource_calculator, self.process_id)
                
                # Verarbeite PDF direkt von der URL für Vorschaubilder
                preview_result: PDFResponse = await pdf_processor.process(
                    file_path=attachments_url,
                    extraction_method='preview'
                )
                
                # Verarbeite PDF nochmal für Textextraktion
                text_result: PDFResponse = await pdf_processor.process(
                    file_path=attachments_url,
                    extraction_method='native'
                )
                
                if preview_result.error:
                    raise ProcessingError(
                        f"Fehler bei der PDF-Vorschau: {preview_result.error.message}",
                        details=preview_result.error.details
                    )
                
                if text_result.error:
                    raise ProcessingError(
                        f"Fehler bei der PDF-Textextraktion: {text_result.error.message}",
                        details=text_result.error.details
                    )
                
                # Extrahiere Vorschaubilder
                gallery_paths: List[str] = []
                if preview_result.data and preview_result.data.metadata.preview_zip:
                    self.logger.info(f"Extrahiere Vorschaubilder aus ZIP: {preview_result.data.metadata.preview_zip}")
                    with zipfile.ZipFile(preview_result.data.metadata.preview_zip, 'r') as zipf:
                        # Liste alle Dateien in der ZIP-Datei auf
                        all_files = zipf.namelist()
                        self.logger.info(f"Dateien in ZIP: {all_files}")
                        
                        # Extrahiere alle Dateien ins Zielverzeichnis
                        zipf.extractall(assets_dir)
                        
                        # Logge die tatsächlich extrahierten Dateien im Dateisystem
                        extracted_files = list(assets_dir.glob('*'))
                        self.logger.info(f"Extrahierte Dateien im Dateisystem: {extracted_files}")
                        
                        # Generiere normalisierte Pfade für die extrahierten Dateien
                        for filename in zipf.namelist():
                            # Verwende nur den Dateinamen ohne Pfad
                            simple_filename = Path(filename).name
                            
                            # Stelle sicher, dass 'assets/' immer mit Forward-Slash gespeichert wird
                            normalized_path = f"assets/{simple_filename}"
                            gallery_paths.append(normalized_path)
                            
                    # Logge die generierten Pfade
                    self.logger.info(f"Generierte Gallery-Pfade: {gallery_paths}")
                
                # Extrahiere Text
                extracted_text = text_result.data.extracted_text if text_result.data else ""
                
                # Kombiniere LLM-Info
                combined_llm_info = LLMInfo(model="pdf-processing", purpose="pdf-processing")
                if preview_result.process and preview_result.process.llm_info:
                    combined_llm_info.add_request(preview_result.process.llm_info.requests)
                if text_result.process and text_result.process.llm_info:
                    combined_llm_info.add_request(text_result.process.llm_info.requests)
                
                self.logger.debug("Anhänge verarbeitet",
                                processing_time=time.time() - start_time,
                                gallery_count=len(gallery_paths),
                                text_length=len(extracted_text or ""))
                
                return gallery_paths, extracted_text or "", combined_llm_info
                
        except Exception as e:
            self.logger.error(f"Fehler bei der Anhang-Verarbeitung: {str(e)}")
            raise ProcessingError(
                f"Fehler bei der Anhang-Verarbeitung: {str(e)}",
                details={
                    "url": attachments_url,
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )

    async def process_event(
        self,
        event: str,
        session: str,
        url: str,
        filename: str,
        track: str,
        day: Optional[str] = None,
        starttime: Optional[str] = None,
        endtime: Optional[str] = None,
        speakers: Optional[List[str]] = None,
        video_url: Optional[str] = None,
        attachments_url: Optional[str] = None,
        source_language: str = "en",
        target_language: str = "de",
        use_cache: bool = True
    ) -> EventResponse:
        """
        Verarbeitet ein Event mit allen zugehörigen Medien.
        
        Args:
            event: Name der Veranstaltung
            session: Name der Session
            url: URL zur Event-Seite
            filename: Zieldateiname für die Markdown-Datei
            track: Track/Kategorie der Session
            day: Optional, Veranstaltungstag im Format YYYY-MM-DD
            starttime: Optional, Startzeit im Format HH:MM
            endtime: Optional, Endzeit im Format HH:MM
            speakers: Optional, Liste der Vortragenden
            video_url: Optional, URL zum Video
            attachments_url: Optional, URL zu Anhängen
            source_language: Optional, Quellsprache (Standard: en)
            target_language: Optional, Zielsprache (Standard: de)
            use_cache: Optional, ob die Ergebnisse zwischengespeichert werden sollen
            
        Returns:
            EventResponse: Das Verarbeitungsergebnis
        """
        total_start_time = time.time()
        try:
            # Eingabedaten validieren
            input_data = EventInput(
                event=event,
                session=session,
                url=url,
                filename=filename,
                track=track,
                day=day,
                starttime=starttime,
                endtime=endtime,
                speakers=speakers or [],
                video_url=video_url,
                attachments_url=attachments_url,
                source_language=source_language,
                target_language=target_language
            )
            
            # LLM-Tracking initialisieren
            llm_info = LLMInfo(model="event-processor", purpose="process-event")
            
            self.logger.info(f"Starte Verarbeitung von Event: {event} - {session}")
            
            # Erstelle formatierten Session-Verzeichnisnamen mit Startzeit
            session_dir_name = f"{Path(filename).stem}"
            
            # Zielverzeichnisstruktur erstellen:
            # events/[event]/[track]/[time-session_dir]
            target_dir: Path = self.base_dir / event / track / session_dir_name
            if not target_dir.exists():
                target_dir.mkdir(parents=True)
            
            # 1. Event-Seite abrufen
            web_text = await self._fetch_event_page(url)
            
            # 2. Video verarbeiten falls vorhanden
            video_transcript = ""
            if video_url:
                video_transcript, video_llm_info = await self._process_video(
                    video_url,
                    source_language,
                    source_language,
                    use_cache
                )
                if video_llm_info:
                    llm_info.add_request(video_llm_info.requests)
        
            # 3. Anhänge verarbeiten falls vorhanden
            gallery_paths = []
            attachment_text = ""
            if attachments_url:
                gallery_paths, attachment_text, attachments_llm_info = await self._process_attachments(
                    attachments_url,
                    input_data,
                    target_dir
                )
                if attachments_llm_info:
                    llm_info.add_request(attachments_llm_info.requests)
            
            # 4. Markdown generieren
            template_context = {
                "event": event,
                "session": session,
                "track": track,
                "day": day,
                "starttime": starttime,
                "endtime": endtime,
                "speakers": speakers or [],
                "url": url,
                "video_url": video_url,
                "video_mp4_url": video_url.replace('.webm', '.mp4') if video_url else None,
                "attachments_url": attachments_url,
                "web_text": web_text,
                "video_transcript": video_transcript,
                "gallery": gallery_paths,
                "attachment_text": attachment_text,  # Füge extrahierten Text hinzu
                "session_dir": session_dir_name
            }
            
            markdown_content, markdown_llm_info = await self._generate_markdown(
                web_text=web_text,
                video_transcript=video_transcript,
                event_data=input_data,
                target_dir=target_dir,
                context=template_context
            )
            if markdown_llm_info:
                llm_info.add_request(markdown_llm_info.requests)
                
            # Markdown-Datei im Session-Verzeichnis speichern
            markdown_file: Path = target_dir / filename
            markdown_file.write_text(markdown_content, encoding='utf-8')
            
            total_processing_time = time.time() - total_start_time
            
            # Output erstellen
            output_data = EventOutput(
                web_text=web_text,
                video_transcript=video_transcript,
                context=template_context,
                markdown_file=str(markdown_file),
                markdown_content=markdown_content,
                attachments_url=attachments_url,
                attachments=gallery_paths,
                metadata={
                    "processed_at": datetime.now().isoformat(),
                    "status": "success",
                    "event": event,
                    "session": session,
                    "track": track,
                    "day": day,
                    "starttime": starttime,
                    "endtime": endtime,
                    "speakers": speakers or [],
                    "has_video": bool(video_url),
                    "has_attachments": bool(attachments_url),
                    "gallery_count": len(gallery_paths),
                    "markdown_length": len(markdown_content),
                    "total_processing_time": total_processing_time,
                    "source_language": source_language,
                    "target_language": target_language
                }
            )
            
            # Response erstellen
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=EventData(
                    input=input_data,
                    output=output_data
                ),
                request_info={
                    "event": event,
                    "session": session,
                    "url": url,
                    "filename": filename,
                    "track": track,
                    "day": day,
                    "starttime": starttime,
                    "endtime": endtime,
                    "speakers": speakers or [],
                    "video_url": video_url,
                    "attachments_url": attachments_url,
                    "source_language": source_language,
                    "target_language": target_language
                },
                response_class=EventResponse,
                llm_info=llm_info,
                from_cache=False
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
            self.logger.error(f"Fehler bei der Event-Verarbeitung: {str(e)}")
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,
                request_info={
                    "event": event,
                    "session": session,
                    "url": url,
                    "filename": filename,
                    "track": track,
                    "source_language": source_language,
                    "target_language": target_language
                },
                response_class=EventResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def process_many_events(
        self,
        events: List[Dict[str, Any]]
    ) -> BatchEventResponse:
        """
        Verarbeitet mehrere Events sequentiell.
        
        Args:
            events: Liste von Event-Daten mit denselben Parametern wie process_event
            
        Returns:
            BatchEventResponse: Ergebnis der Batch-Verarbeitung
        """
        start_time = time.time()
        
        try:
            # Initialisiere Listen für Ergebnisse und Fehler
            successful_outputs: List[EventOutput] = []
            errors: List[Dict[str, Any]] = []
            llm_infos: List[LLMInfo] = []
            
            # Verarbeite Events sequentiell
            for i, event_data in enumerate(events):
                try:
                    # Verarbeite einzelnes Event
                    result = await self.process_event(
                        event=event_data.get("event", ""),
                        session=event_data.get("session", ""),
                        url=event_data.get("url", ""),
                        filename=event_data.get("filename", ""),
                        track=event_data.get("track", ""),
                        day=event_data.get("day"),
                        starttime=event_data.get("starttime"),
                        endtime=event_data.get("endtime"),
                        speakers=event_data.get("speakers", []),
                        video_url=event_data.get("video_url"),
                        attachments_url=event_data.get("attachments_url"),
                        source_language=event_data.get("source_language", "en"),
                        target_language=event_data.get("target_language", "de")
                    )
                    
                    # Sammle erfolgreiche Ergebnisse
                    if result.data and result.data.output:
                        successful_outputs.append(result.data.output)
                    if result.process.llm_info:
                        llm_infos.append(result.process.llm_info)
                        
                except Exception as e:
                    # Protokolliere Fehler, aber setze Verarbeitung fort
                    errors.append({
                        "index": i,
                        "event": event_data.get("event", "unknown"),
                        "error": str(e)
                    })
                    self.logger.error(
                        f"Fehler bei der Verarbeitung von Event {i}",
                        error=e,
                        event=event_data.get("event", "unknown")
                    )
            
            # Erstelle BatchEventOutput
            batch_output = BatchEventOutput(
                results=successful_outputs,
                summary={
                    "total_events": len(events),
                    "successful": len(successful_outputs),
                    "failed": len(errors),
                    "errors": errors,
                    "processing_time": time.time() - start_time
                }
            )
            
            # Erstelle BatchEventData
            batch_data = BatchEventData(
                input=BatchEventInput(events=events),
                output=batch_output
            )
            
            # Kombiniere alle LLM-Infos
            combined_llm_info = None
            if llm_infos:
                combined_llm_info = llm_infos[0]
                for info in llm_infos[1:]:
                    combined_llm_info = combined_llm_info.merge(info)
            
            # Erstelle Response
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=batch_data,
                request_info={
                    "event_count": len(events),
                    "successful": len(successful_outputs),
                    "failed": len(errors)
                },
                response_class=BatchEventResponse,
                llm_info=combined_llm_info,
                from_cache=False
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
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,
                request_info={
                    "event_count": len(events)
                },
                response_class=BatchEventResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def process_notion_blocks(
        self,
        blocks: List[Dict[str, Any]]
    ) -> NotionResponse:
        """
        Verarbeitet Notion Blocks und erstellt mehrsprachigen Newsfeed-Inhalt.
        Die Quellsprache ist fest auf Deutsch eingestellt, die Zielsprache ist Italienisch.
        
        Args:
            blocks: Liste der Notion Blocks
            
        Returns:
            NotionResponse mit verarbeitetem Newsfeed-Inhalt
        """
        try:
            self.logger.info("Starte Verarbeitung von Notion Blocks",
                           block_count=len(blocks))

            # Validiere und konvertiere Blocks
            notion_blocks: List[NotionBlock] = []
            for block in blocks:
                # Entferne nicht benötigte Felder und extrahiere verschachtelte Werte
                root_id = str(block.get("root_id") or "")
                object_type = str(block.get("object") or "")
                block_id = str(block.get("id") or "")
                parent_id = str(block.get("parent", {}).get("page_id") or "")
                block_type = str(block.get("type") or "")
                has_children = bool(block.get("has_children"))
                archived = bool(block.get("archived"))
                in_trash = bool(block.get("in_trash"))
                content = str(block.get("content") or "")
                image = block.get("image") if block.get("type") == "image" else None
                caption = str(block.get("caption") or "")
                
                notion_block = NotionBlock(
                    root_id=root_id,
                    object=object_type,
                    id=block_id,
                    parent_id=parent_id,
                    type=block_type,
                    has_children=has_children,
                    archived=archived,
                    in_trash=in_trash,
                    content=content,
                    image=image,
                    caption=caption
                )
                
                # Debug-Logging für Block-Struktur
                self.logger.debug("Block-Struktur:",
                                block_type=block_type,
                                has_content=bool(content),
                                raw_block=block)
                
                notion_blocks.append(notion_block)
            
            self.logger.debug("Notion Blocks validiert und konvertiert",
                            block_count=len(notion_blocks))
            
            # Extrahiere ID vom ersten Block
            newsfeed_id = notion_blocks[0].root_id if notion_blocks else ""
            if not newsfeed_id:
                self.logger.warning("Keine parent_id im ersten Block gefunden")
            
            # Sammle deutschen Content (alles vor "Content_IT:")
            content_de: List[str] = []
            content_it: List[str] = []
            is_italian_content = False
            
            for block in notion_blocks:
                if block.type == "paragraph":
                    if block.content == "Content_IT:":
                        is_italian_content = True
                        continue
                        
                    if block.content:
                        if is_italian_content:
                            content_it.append(block.content)
                        else:
                            content_de.append(block.content)
            
            if not content_de:
                self.logger.warning("Kein deutscher Content gefunden")
            if not content_it:
                self.logger.warning("Kein italienischer Content gefunden")
                
            # Extrahiere Titel und Intro aus deutschem Content
            title_de = content_de[0].split('.')[0] if content_de else ""
            intro_de = content_de[0] if content_de else ""
            
            # Extrahiere Titel und Intro aus italienischem Content
            title_it = content_it[0] if content_it else ""
            intro_it = content_it[0] if content_it else ""
            
            # Extrahiere Bild-URL
            image_url = None
            for block in notion_blocks:
                if block.type == "image" and block.image:
                    image_url = block.image.get("file", {}).get("url", "")
                    break
            
            # Erstelle Newsfeed
            newsfeed = Newsfeed(
                id=newsfeed_id,
                title_DE=title_de,
                intro_DE=intro_de,
                title_IT=title_it,
                intro_IT=intro_it,
                image=image_url,
                content_DE="\n\n".join(content_de),
                content_IT="\n\n".join(content_it)
            )
            self.logger.debug("Newsfeed erstellt",
                            has_image=bool(image_url),
                            content_de_length=len(content_de),
                            content_it_length=len(content_it))
            
            # Erstelle NotionData
            notion_data = NotionData(
                input=notion_blocks,
                output=newsfeed
            )
            
            self.logger.info("Notion Block Verarbeitung erfolgreich abgeschlossen")
            
            # Erstelle Response
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=notion_data,
                request_info={
                    "block_count": len(blocks)
                },
                response_class=NotionResponse,
                llm_info=None,  # Keine LLM-Nutzung in diesem Fall
                from_cache=False
            )
            
        except Exception as e:
            self.logger.error("Fehler bei der Notion Block Verarbeitung",
                            error=e,
                            error_type=type(e).__name__,
                            traceback=traceback.format_exc())
            
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,
                request_info={
                    "block_count": len(blocks)
                },
                response_class=NotionResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def _send_webhook_callback(
        self,
        webhook_config: WebhookConfig,
        event_output: EventOutput,
        event_input: EventInput,
        success: bool = True,
        error: Union[str, Exception, None] = None
    ) -> bool:
        """
        Sendet einen Webhook-Callback mit den Ergebnissen der Event-Verarbeitung.
        
        Args:
            webhook_config: Konfiguration des Webhooks
            event_output: Output der Event-Verarbeitung
            event_input: Input der Event-Verarbeitung
            success: Flag ob die Verarbeitung erfolgreich war
            error: Optional, Fehlermeldung falls nicht erfolgreich
            
        Returns:
            bool: True wenn der Webhook erfolgreich gesendet wurde
        """
        try:
            # Konvertiere Exception zu String für API-Kompatibilität
            error_str = str(error) if error is not None else None
            
            # Erstelle Webhook-Payload
            payload = {
                "status": "success" if success else "error",
                "event": {
                    "name": event_input.event,
                    "session": event_input.session,
                    "url": event_input.url,
                    "track": event_input.track,
                    "speakers": event_input.speakers
                },
                "result": {
                    "markdown_content": event_output.markdown_content,
                    "markdown_file": event_output.markdown_file,
                    "metadata": event_output.metadata
                },
                "error": error_str,
                "timestamp": datetime.now().isoformat()
            }
            
            # Sende den Webhook
            headers = {
                "Content-Type": "application/json",
                **webhook_config.headers
            }
            
            self.logger.info(f"WEBHOOK-DEBUG: Webhook-Payload vorbereitet für: {event_input.session}, Größe: {len(str(payload))} Bytes")
            
            response = requests.post(
                webhook_config.url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            self.logger.info(f"WEBHOOK-DEBUG: Webhook-Response-Status: {response.status_code} für Event: {event_input.session}")
            
            try:
                response.raise_for_status()
                self.logger.info(f"WEBHOOK-DEBUG: Webhook erfolgreich gesendet: {response.status_code} für: {event_input.session}")
                return True
            except requests.exceptions.HTTPError as http_err:
                self.logger.error(f"WEBHOOK-DEBUG: HTTP-Fehler beim Senden des Webhooks: {http_err}, Status: {response.status_code}, Response: {response.text[:200]}")
                return False
            
        except Exception as e:
            self.logger.error(f"WEBHOOK-DEBUG: Fehler beim Senden des Webhooks: {str(e)} für: {event_input.session}")
            self.logger.error(f"WEBHOOK-DEBUG: Webhook-Fehler Traceback: {traceback.format_exc()}")
            return False

    async def process_event_async(
        self,
        event: str,
        session: str,
        url: str,
        filename: str,
        track: str,
        webhook_url: str,
        day: Optional[str] = None,
        starttime: Optional[str] = None,
        endtime: Optional[str] = None,
        speakers: Optional[List[str]] = None,
        video_url: Optional[str] = None,
        attachments_url: Optional[str] = None,
        source_language: str = "en",
        target_language: str = "de",
        webhook_headers: Optional[Dict[str, str]] = None,
        include_markdown: bool = True,
        include_metadata: bool = True,
        event_id: Optional[str] = None,
        use_cache: bool = True
    ) -> EventResponse:
        """
        Verarbeitet ein Event asynchron und sendet einen Webhook-Callback nach Abschluss.
        
        Args:
            event: Name der Veranstaltung
            session: Name der Session
            url: URL zur Event-Seite
            filename: Zieldateiname für die Markdown-Datei
            track: Track/Kategorie der Session
            webhook_url: URL für den Webhook-Callback
            day: Optional, Veranstaltungstag im Format YYYY-MM-DD
            starttime: Optional, Startzeit im Format HH:MM
            endtime: Optional, Endzeit im Format HH:MM
            speakers: Optional, Liste der Vortragenden
            video_url: Optional, URL zum Video
            attachments_url: Optional, URL zu Anhängen
            source_language: Optional, Quellsprache (Standard: en)
            target_language: Optional, Zielsprache (Standard: de)
            webhook_headers: Optional, HTTP-Header für den Webhook
            include_markdown: Optional, ob der Markdown-Inhalt im Webhook enthalten sein soll
            include_metadata: Optional, ob die Metadaten im Webhook enthalten sein soll
            event_id: Optional, eine eindeutige ID für das Event
            use_cache: Optional, ob die Ergebnisse zwischengespeichert werden sollen
            
        Returns:
            EventResponse: Eine sofortige Antwort, dass das Event zur Verarbeitung angenommen wurde
        """
        try:
            # Erstelle Webhook-Konfiguration
            webhook_config = WebhookConfig(
                url=webhook_url,
                headers=webhook_headers or {},
                include_markdown=include_markdown,
                include_metadata=include_metadata,
                event_id=event_id or str(uuid.uuid4())
            )
            
            # Erstelle Eingabedaten
            input_data = AsyncEventInput(
                event=event,
                session=session,
                url=url,
                filename=filename,
                track=track,
                day=day,
                starttime=starttime,
                endtime=endtime,
                speakers=speakers or [],
                video_url=video_url,
                attachments_url=attachments_url,
                source_language=source_language,
                target_language=target_language,
                webhook=webhook_config,
                use_cache=use_cache
            )
            
            # Starte die asynchrone Verarbeitung in einem separaten Task
            asyncio.create_task(self._process_event_async_task(input_data))
            
            # Erstelle eine sofortige Antwort
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,  # Keine Daten, da die Verarbeitung asynchron erfolgt
                request_info={
                    "event": event,
                    "session": session,
                    "url": url,
                    "filename": filename,
                    "track": track,
                    "day": day,
                    "starttime": starttime,
                    "endtime": endtime,
                    "speakers": speakers or [],
                    "video_url": video_url,
                    "attachments_url": attachments_url,
                    "source_language": source_language,
                    "target_language": target_language,
                    "webhook_url": webhook_url,
                    "event_id": webhook_config.event_id,
                    "async_processing": True
                },
                response_class=EventResponse,
                from_cache=False
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
            self.logger.error(f"Fehler bei der asynchronen Event-Verarbeitung: {str(e)}")
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,
                request_info={
                    "event": event,
                    "session": session,
                    "url": url,
                    "filename": filename,
                    "track": track,
                    "webhook_url": webhook_url,
                    "async_processing": True
                },
                response_class=EventResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def _process_event_async_task(self, input_data: AsyncEventInput) -> None:
        """
        Interne Methode zur asynchronen Verarbeitung eines Events und Senden des Webhook-Callbacks.
        Verwendet eine Semaphore zur Begrenzung gleichzeitiger Verarbeitungen.
        
        Args:
            input_data: Die Eingabedaten für die Event-Verarbeitung
        """
        # Hol den Performance-Tracker
        tracker = get_performance_tracker()
        
        # Logging: Start der Event-Verarbeitung
        self.logger.info(f"EVENT-DEBUG: Starte Event-Verarbeitung: {input_data.event} - {input_data.session}")
        
        # Event-Metadaten für den Event-Monitor setzen, BEVOR wir mit der Performance-Messung beginnen
        if tracker is not None:
            # Event-Metadaten für den Event-Monitor setzen
            tracker.set_event_metadata(
                event=input_data.event,
                track=input_data.track,
                session=input_data.session
            )            
            # Debug-Logging hinzufügen
            self.logger.info("DEBUG: Performance-Tracker erfolgreich abgerufen")
            self.logger.info(f"DEBUG: Tracker process_id: {tracker.process_id}")
            self.logger.info(f"DEBUG: Tracker processor: {tracker.processor_name}")
            self.logger.info(f"DEBUG: Tracker async: {tracker.async_processing}")
        
        # Semaphore für die Verarbeitung
        semaphore_acquired = False
        
        try:
            # Logging: Vor dem Semaphore-Acquire
            self.logger.info(f"EVENT-DEBUG: Warte auf Semaphore für: {input_data.session}, aktuell verfügbar: {self._processing_semaphore._value}")
            
            # Explizit Semaphore erwerben statt async with
            await self._processing_semaphore.acquire()
            semaphore_acquired = True
            
            # Logging: Nach dem Semaphore-Acquire
            self.logger.info(f"EVENT-DEBUG: Semaphore erhalten für: {input_data.session}, aktuell verfügbar: {self._processing_semaphore._value}")
            
            # Wichtig: Hier messen wir die gesamte Operation
            with tracker.measure_operation('async_event_processing', 'event') if tracker else nullcontext():
                self.logger.info(f"EVENT-DEBUG: Innerhalb der measure_operation für: {input_data.session}")
                try:
                    # Verarbeite das Event
                    self.logger.info(f"Starte asynchrone Verarbeitung von Event: {input_data.event} - {input_data.session}")
                    
                    # Extrahiere die Basis-EventInput-Daten (ohne Webhook)
                    event_input = EventInput(
                        event=input_data.event,
                        session=input_data.session,
                        url=input_data.url,
                        filename=input_data.filename,
                        track=input_data.track,
                        day=input_data.day,
                        starttime=input_data.starttime,
                        endtime=input_data.endtime,
                        speakers=input_data.speakers,
                        video_url=input_data.video_url,
                        attachments_url=input_data.attachments_url,
                        source_language=input_data.source_language,
                        target_language=input_data.target_language
                    )
                    
                    # Logging: Vor process_event
                    self.logger.info(f"EVENT-DEBUG: Rufe process_event auf für: {input_data.session}")
                    
                    # Verarbeite das Event mit der regulären Methode
                    with tracker.measure_operation('process_event', 'event') if tracker else nullcontext():
                        result: EventResponse = await self.process_event(
                            event=input_data.event,
                            session=input_data.session,
                            url=input_data.url,
                            filename=input_data.filename,
                            track=input_data.track,
                            day=input_data.day,
                            starttime=input_data.starttime,
                            endtime=input_data.endtime,
                            speakers=input_data.speakers,
                            video_url=input_data.video_url,
                            attachments_url=input_data.attachments_url,
                            source_language=input_data.source_language,
                            target_language=input_data.target_language,
                            use_cache=input_data.use_cache
                        )
                    
                    # Logging: Nach process_event
                    self.logger.info(f"EVENT-DEBUG: process_event abgeschlossen für: {input_data.session}, Status: {result.status}")
                    
                    # Sende Webhook-Callback bei Erfolg
                    if result.status == ProcessingStatus.SUCCESS and result.data and input_data.webhook:
                        self.logger.info(f"EVENT-DEBUG: Sende Erfolgs-Webhook für: {input_data.session}")
                        with tracker.measure_operation('send_webhook_success', 'event') if tracker else nullcontext():
                            webhook_success = await self._send_webhook_callback(
                                webhook_config=input_data.webhook,
                                event_output=result.data.output,
                                event_input=event_input,
                                success=True
                            )
                            self.logger.info(f"EVENT-DEBUG: Webhook gesendet für: {input_data.session}, Erfolg: {webhook_success}")
                    # Sende Webhook-Callback bei Fehler
                    elif input_data.webhook:
                        self.logger.info(f"EVENT-DEBUG: Sende Fehler-Webhook für: {input_data.session}")
                        with tracker.measure_operation('send_webhook_error', 'event') if tracker else nullcontext():
                            error_message = result.error.message if result.error else "Unbekannter Fehler"
                            webhook_success = await self._send_webhook_callback(
                                webhook_config=input_data.webhook,
                                event_output=self._create_empty_event_output(),
                                event_input=event_input,
                                success=False,
                                error=error_message
                            )
                            self.logger.info(f"EVENT-DEBUG: Fehler-Webhook gesendet für: {input_data.session}, Erfolg: {webhook_success}")
                        
                except Exception as e:
                    self.logger.error(f"EVENT-DEBUG: Fehler bei der asynchronen Event-Verarbeitung: {str(e)}")
                    self.logger.error(f"EVENT-DEBUG: Traceback: {traceback.format_exc()}")
                    
                    # Sende Webhook-Callback bei Ausnahme, falls Webhook konfiguriert
                    if input_data.webhook:
                        try:
                            self.logger.info(f"EVENT-DEBUG: Sende Exception-Webhook für: {input_data.session}")
                            with tracker.measure_operation('send_webhook_exception', 'event') if tracker else nullcontext():
                                error_exception = Exception(str(e))
                                webhook_success = await self._send_webhook_callback(
                                    webhook_config=input_data.webhook,
                                    event_output=self._create_empty_event_output(),
                                    event_input=EventInput(
                                        event=input_data.event,
                                        session=input_data.session,
                                        url=input_data.url,
                                        filename=input_data.filename,
                                        track=input_data.track
                                    ),
                                    success=False,
                                    error=error_exception
                                )
                                self.logger.info(f"EVENT-DEBUG: Exception-Webhook gesendet für: {input_data.session}, Erfolg: {webhook_success}")
                        except Exception as webhook_error:
                            self.logger.error(
                                f"Fehler beim Senden des Fehler-Webhooks für Event {input_data.session}: {str(webhook_error)}",
                                event_id=input_data.session,
                                error_type=type(webhook_error).__name__,
                                error_message=str(webhook_error),
                                traceback=traceback.format_exc()
                            )
                
                # WICHTIG: Stellen Sie sicher, dass das Semaphore IMMER freigegeben wird, aber erst NACH Abschluss der Verarbeitung
                if semaphore_acquired:
                    self._processing_semaphore.release()
                    self.logger.info(f"EVENT-DEBUG: Semaphore freigegeben für: {input_data.session}, aktuell verfügbar: {self._processing_semaphore._value}")
        except Exception as e:
            # Logging im Falle eines Fehlers vor/während des Semaphore-Locks
            self.logger.error(f"EVENT-DEBUG: Kritischer Fehler außerhalb des Semaphore-Blocks: {str(e)}")
            self.logger.error(f"EVENT-DEBUG: Kritischer Fehler Traceback: {traceback.format_exc()}")
            
            # Semaphore nur freigeben, wenn es erworben wurde und noch nicht freigegeben wurde
            if semaphore_acquired:
                self._processing_semaphore.release()
                self.logger.info(f"EVENT-DEBUG: Semaphore freigegeben nach kritischem Fehler für: {input_data.session}, aktuell verfügbar: {self._processing_semaphore._value}")
            
        # Logging: Ende der Event-Verarbeitung
        self.logger.info(f"EVENT-DEBUG: Event-Verarbeitung abgeschlossen: {input_data.session}")

    async def _process_many_events_async_task(self, input_data: AsyncBatchEventInput) -> None:
        """
        Task für die asynchrone Verarbeitung mehrerer Events.
        
        Erstellt Jobs in der MongoDB und startet den Worker-Manager.
        
        Args:
            input_data: Eingabedaten für die Event-Verarbeitung
        """
        from src.core.mongodb import get_job_repository
        from typing import List
        
        self.logger.info(
            "Starte asynchrone Batchverarbeitung über MongoDB",
            event_count=len(input_data.events)
        )
        
        # Job-Repository holen
        job_repo = get_job_repository()
        
        # Batch erstellen
        batch_data = {
            "total_jobs": len(input_data.events),
            "webhook": input_data.webhook.to_dict() if input_data.webhook else None
        }
        
        batch_id = job_repo.create_batch(batch_data)
        
        # Jobs für jedes Event erstellen
        job_ids: List[str] = []
        for event_index, event in enumerate(input_data.events):
            # Event-Daten validieren
            event_data = self._validate_event_data(event)
            if not event_data:
                self.logger.warning(
                    f"Ungültige Event-Daten, überspringe Event {event_index}",
                    event_id=event_index
                )
                continue
                
            # Stelle sicher, dass alle notwendigen Parameter vorhanden sind
            # Besonders wichtig: source_language, target_language und video_url für die Template-Transformation
            if "source_language" not in event_data:
                event_data["source_language"] = "en"
            if "target_language" not in event_data:
                event_data["target_language"] = "de"
            
            # Job erstellen
            job_data = {
                "batch_id": batch_id,
                "parameters": event_data,
                "webhook": input_data.webhook.to_dict() if input_data.webhook else None
            }
            
            job_id = job_repo.create_job(job_data)
            job_ids.append(job_id)
            
            self.logger.info(
                f"Job erstellt für Event {event_index+1}/{len(input_data.events)}: {event_data.get('session', 'Unbekannt')}",
                job_id=job_id,
                event_id=event_index
            )
        
        self.logger.info(
            f"Batch-Job erstellt mit ID {batch_id}, {len(job_ids)} Events in die Queue eingereiht"
        )
        
        return

    def _validate_event_data(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validiert die Event-Daten und gibt ein bereinigtes Dictionary zurück.
        
        Args:
            event: Die zu validierenden Event-Daten
            
        Returns:
            Optional[Dict[str, Any]]: Die validierten Daten oder None, wenn die Daten ungültig sind
        """
        if not event:
            self.logger.warning("Event-Daten sind leer")
            return None
        
        # Prüfe, ob mindestens Pflichtfelder vorhanden sind
        required_fields = ["event", "session"]
        for field in required_fields:
            if field not in event or not event[field]:
                self.logger.warning(f"Pflichtfeld '{field}' fehlt in Event-Daten oder ist leer")
                return None
        
        return event

    async def process_many_events_async(
        self,
        events: List[Dict[str, Any]],
        webhook_url: str,
        webhook_headers: Optional[Dict[str, str]] = None,
        include_markdown: bool = True,
        include_metadata: bool = True,
        batch_id: Optional[str] = None
    ) -> BatchEventResponse:
        """
        Verarbeitet mehrere Events asynchron und sendet Webhook-Callbacks nach Abschluss jedes Events.
        
        Verwendet die MongoDB-basierte Job-Verwaltung für die asynchrone Verarbeitung.
        
        Args:
            events: Liste von Event-Daten mit denselben Parametern wie process_event
            webhook_url: URL für den Webhook-Callback
            webhook_headers: Optional, HTTP-Header für den Webhook
            include_markdown: Optional, ob der Markdown-Inhalt im Webhook enthalten sein soll
            include_metadata: Optional, ob die Metadaten im Webhook enthalten sein soll
            batch_id: Optional, eine eindeutige ID für den Batch
            
        Returns:
            BatchEventResponse: Eine sofortige Antwort, dass die Events zur Verarbeitung angenommen wurden
        """
        try:
            # Erstelle Webhook-Konfiguration
            webhook_config = WebhookConfig(
                url=webhook_url,
                headers=webhook_headers or {},
                include_markdown=include_markdown,
                include_metadata=include_metadata,
                event_id=batch_id or str(uuid.uuid4())
            )
            
            # Erstelle Eingabedaten
            input_data = AsyncBatchEventInput(
                events=events,
                webhook=webhook_config
            )
            
            # Starte die asynchrone Verarbeitung in einem separaten Task
            # Speichere die Task-Referenz, damit sie nicht vom Garbage Collector entfernt wird
            processing_task = asyncio.create_task(self._process_many_events_async_task(input_data))
            
            # Fehlerbehandlung über einen zusätzlichen Task, der bei Ausnahmen loggt
            async def handle_task_exception(task: asyncio.Task[None]) -> None:
                try:
                    await task
                except Exception as e:
                    self.logger.error(f"CRITICAL-DEBUG: Unbehandelte Ausnahme in Batch-Task: {str(e)}")
                    self.logger.error(f"CRITICAL-DEBUG: Traceback: {traceback.format_exc()}")
            
            # Starte Überwachungs-Task und bewahre die Referenz auf
            monitoring_task = asyncio.create_task(handle_task_exception(processing_task))
            
            # Speichere beide Tasks im Klassenvariablen-Dict, um sie vor Garbage Collection zu schützen
            if not hasattr(self, '_background_tasks'):
                self._background_tasks: List[asyncio.Task[Any]] = []
            self._background_tasks.append(processing_task)
            self._background_tasks.append(monitoring_task)
            
            # Log zur Bestätigung
            self.logger.info(f"BATCH-DEBUG: MongoDB-Batch-Task gestartet und im Hintergrund gespeichert. Aktive Tasks: {len(self._background_tasks)}")
            
            # Erstelle eine sofortige Antwort
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=BatchEventData(
                    input=BatchEventInput(events=events),
                    output=BatchEventOutput(
                        results=[],
                        summary={
                            "total_events": len(events),
                            "status": "accepted",
                            "batch_id": webhook_config.event_id,
                            "webhook_url": webhook_url,
                            "async_processing": True,
                            "processing_type": "mongodb"
                        }
                    )
                ),
                request_info={
                    "event_count": len(events),
                    "webhook_url": webhook_url,
                    "batch_id": webhook_config.event_id,
                    "async_processing": True,
                    "processing_type": "mongodb"
                },
                response_class=BatchEventResponse,
                llm_info=None,
                from_cache=False
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
            self.logger.error(f"Fehler bei der asynchronen Batch-Event-Verarbeitung: {str(e)}")
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.EVENT.value,
                result=None,
                request_info={
                    "event_count": len(events),
                    "webhook_url": webhook_url,
                    "async_processing": True,
                    "processing_type": "mongodb"
                },
                response_class=BatchEventResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    def _create_empty_event_output(self) -> EventOutput:
        """Erstellt eine leere EventOutput-Instanz für Fehlerfälle."""
        return EventOutput(
            web_text="",
            video_transcript="",
            context={},
            markdown_file="",
            markdown_content=""
        )
