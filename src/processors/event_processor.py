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
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import traceback
import time
import requests
from bs4 import BeautifulSoup
import zipfile

from processors.pdf_processor import PDFResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.video import VideoResponse
from src.core.models.event import (
    EventInput, EventOutput, EventData, EventResponse, BatchEventResponse, BatchEventOutput, BatchEventData, BatchEventInput
)
from src.core.models.base import (
     ErrorInfo
)
from src.core.models.llm import LLMInfo
from src.core.models.enums import ProcessorType
from src.core.exceptions import ProcessingError
from src.core.models.response_factory import ResponseFactory
from src.processors.video_processor import VideoProcessor
from src.processors.transformer_processor import TransformerProcessor
from .base_processor import BaseProcessor
from src.processors.pdf_processor import PDFProcessor
from src.core.models.notion import NotionBlock, NotionResponse, NotionData, Newsfeed

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
                
            # Temporäres Verzeichnis einrichten
            self.init_temp_dir("event", event_config)
            
            # Initialisiere Sub-Prozessoren
            self.video_processor = VideoProcessor(resource_calculator, process_id)
            self.transformer_processor = TransformerProcessor(resource_calculator, process_id)
            
            self.logger.debug("Event Processor initialisiert",
                            base_dir=str(self.base_dir),
                            temp_dir=str(self.temp_dir))
                            
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
        try:
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

    async def _process_video(self, video_url: str, source_language: str, target_language: str) -> Tuple[str, Optional[LLMInfo]]:
        """
        Lädt das Video herunter und extrahiert die Audio-Transkription.
        
        Args:
            video_url: URL zum Video
            source_language: Quellsprache des Videos
            
        Returns:
            Tuple aus transkribiertem Text und LLM-Info
        """
        start_time: float = time.time()
        try:
            self.logger.info(f"Verarbeite Video: {video_url}")
            
            # Video in Quellsprache verarbeiten
            result: VideoResponse = await self.video_processor.process(
                source=video_url,
                source_language=source_language,
                target_language=target_language  
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
        try:
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
                source_text=video_transcript,
                source_language=event_data.target_language, # video_transcript ist schon übersetzt
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
        try:
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
                with zipfile.ZipFile(preview_result.data.metadata.preview_zip, 'r') as zipf:
                    zipf.extractall(assets_dir)
                    for filename in zipf.namelist():
                        gallery_paths.append(str(Path("assets") / filename))
            
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
        target_language: str = "de"
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
            session_time = starttime.replace(':', '') if starttime else '0000'
            session_dir_name = f"{day}-{session_time}-{Path(filename).stem}"
            
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
                    target_language
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
                markdown_file=str(markdown_file),
                markdown_content=markdown_content,
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
                error=error_info
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
                llm_info=combined_llm_info
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
                error=error_info
            )

    async def process_notion_blocks(
        self,
        blocks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Verarbeitet Notion Blocks und erstellt mehrsprachigen Newsfeed-Inhalt.
        Die Quellsprache ist fest auf Deutsch eingestellt, die Zielsprache ist Italienisch.
        
        Args:
            blocks: Liste der Notion Blocks
            
        Returns:
            Dict[str, Any]: Response als Dictionary
        """
        try:
            self.logger.info("Starte Verarbeitung von Notion Blocks",
                           block_count=len(blocks))

            # Validiere und konvertiere Blocks
            notion_blocks = []
            for block in blocks:
                # Entferne nicht benötigte Felder und extrahiere verschachtelte Werte
                cleaned_block = {
                    "root_id": block.get("root_id", ""),
                    "object": block.get("object", ""),
                    "id": block.get("id", ""),
                    "parent_id": block.get("parent", {}).get("page_id", ""),
                    "type": block.get("type", ""),
                    "has_children": block.get("has_children", False),
                    "archived": block.get("archived", False),
                    "in_trash": block.get("in_trash", False),
                    "content": block.get("content", ""),
                    "image": block.get("image", None) if block.get("type") == "image" else None,
                    "caption": block.get("caption", "")
                }
                
                # Debug-Logging für Block-Struktur
                self.logger.debug("Block-Struktur:",
                                block_type=block.get("type"),
                                has_content=bool(cleaned_block["content"]),
                                raw_block=block)
                
                notion_blocks.append(NotionBlock(**cleaned_block))
            
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
                llm_info=None  # Keine LLM-Nutzung in diesem Fall
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
                error=error_info
            ) 