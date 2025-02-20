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
5. Rückgabe der Verarbeitungsergebnisse
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import traceback
import requests
from bs4 import BeautifulSoup

from core.models.transformer import TransformerResponse
from core.models.video import VideoResponse
from src.core.models.event import (
    EventInput, EventOutput, EventData, EventResponse
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
            Tuple aus HTML-Body und extrahiertem Text
        """
        try:
            self.logger.info(f"Rufe Event-Seite ab: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response: requests.Response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extrahiere Body und Text
            text = soup.get_text(separator='\n', strip=True)
            
            return text  # Return raw HTML und extrahierten Text
            
        except Exception as e:
            self.logger.error(f"Fehler beim Abrufen der Event-Seite: {str(e)}")
            raise ProcessingError(f"Fehler beim Abrufen der Event-Seite: {str(e)}")

    async def _process_video(self, video_url: str) -> Tuple[str, Optional[LLMInfo]]:
        """
        Lädt das Video herunter und extrahiert die Audio-Transkription.
        
        Args:
            video_url: URL zum Video
            
        Returns:
            Tuple aus transkribiertem Text und LLM-Info
        """
        try:
            self.logger.info(f"Verarbeite Video: {video_url}")
            
            # Video verarbeiten
            result: VideoResponse = await self.video_processor.process(
                source=video_url,
                target_language="de",  # Könnte später konfigurierbar sein
                source_language="auto"
            )
            
            if result.error:
                raise ProcessingError(f"Fehler bei der Video-Verarbeitung: {result.error.message}")
                
            # Extrahiere Transkription und LLM-Info
            transcription = ""
            if result.data and result.data.transcription:
                transcription = result.data.transcription.text if hasattr(result.data.transcription, 'text') else ''
            
            return transcription, result.process.llm_info
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Video-Verarbeitung: {str(e)}")
            raise ProcessingError(f"Fehler bei der Video-Verarbeitung: {str(e)}")

    async def _generate_markdown(
        self,
        web_text: str,
        video_transcript: str,
        event_data: EventInput
    ) -> Tuple[str, Optional[LLMInfo]]:
        """
        Generiert die Markdown-Datei mit allen Informationen.
        
        Args:
            html_body: HTML der Event-Seite
            extracted_text: Extrahierter Text der Event-Seite
            video_transcript: Transkription des Videos
            event_data: Event-Metadaten
            
        Returns:
            Tuple aus generiertem Markdown-Text und LLM-Info
        """
        try:
            self.logger.info("Generiere Markdown")
            
            # Kontext für Template vorbereiten
            context = {
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
                "web_text": web_text
            }
            
            # Template-Transformation durchführen
            result: TransformerResponse = self.transformer_processor.transformByTemplate(
                source_text=video_transcript,
                source_language="en",
                target_language="en",
                template="Event",
                context=context
            )
            
            if result.error:
                raise ProcessingError(f"Fehler bei der Markdown-Generierung: {result.error.message}")
                
            return result.data.output.text, result.process.llm_info
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Markdown-Generierung: {str(e)}")
            raise ProcessingError(f"Fehler bei der Markdown-Generierung: {str(e)}")

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
        attachments_url: Optional[str] = None
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
            
        Returns:
            EventResponse: Das Verarbeitungsergebnis
        """
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
                attachments_url=attachments_url
            )
            
            # LLM-Tracking initialisieren
            llm_info = LLMInfo(model="event-processor", purpose="process-event")
            
            self.logger.info(f"Starte Verarbeitung von Event: {event} - {session}")
            
            # 1. Event-Seite abrufen
            web_text = await self._fetch_event_page(url)
            
            # 2. Video verarbeiten falls vorhanden
            video_transcript = ""
            if video_url:
                video_transcript, video_llm_info = await self._process_video(video_url) 
                if video_llm_info:
                    llm_info.add_request(video_llm_info.requests)
            
            # 3. Markdown generieren
            markdown_content, markdown_llm_info = await self._generate_markdown(
                web_text=web_text,
                video_transcript=video_transcript,
                event_data=input_data
            )
            if markdown_llm_info:
                llm_info.add_request(markdown_llm_info.requests)
            
            # Zielverzeichnis erstellen
            target_dir: Path = self.base_dir / track
            if not target_dir.exists():
                target_dir.mkdir(parents=True)
                
            # Markdown-Datei speichern
            markdown_file: Path = target_dir / filename
            markdown_file.write_text(markdown_content, encoding='utf-8')
            
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
                    "markdown_length": len(markdown_content)
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
                    "attachments_url": attachments_url
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
                    "track": track
                },
                response_class=EventResponse,
                error=error_info
            ) 