"""
Session-Processor Modul.
Verarbeitet Session-Informationen und zugehörige Medien.

Funktionalität:
--------------
1. Extrahiert Session-Informationen von der Session-Seite
2. Lädt zugehörige Medien (Videos, Anhänge) herunter
3. Transformiert und speichert alles in einer strukturierten Form
4. Generiert eine Markdown-Datei mit allen Informationen

Ablauf:
-------
1. Validierung der Eingabeparameter
2. Abrufen und Parsen der Session-Seite
3. Download und Verarbeitung der Medien
4. Generierung der Markdown-Datei
5. Finale Übersetzung in Zielsprache
6. Rückgabe der Verarbeitungsergebnisse mit Performance-Metriken
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, TypeVar
from pathlib import Path
import traceback
import time
import requests
from bs4 import BeautifulSoup
import asyncio
import uuid
from contextlib import nullcontext
import json
import shutil

from src.processors.pdf_processor import PDFResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.video import VideoResponse
from src.core.models.session import (
    SessionInput, SessionOutput, SessionData, SessionResponse, BatchSessionResponse, BatchSessionOutput, BatchSessionData, BatchSessionInput,
    WebhookConfig, AsyncBatchSessionInput
)
from src.core.models.base import (
     ErrorInfo
)
from src.core.models.llm import LLMInfo
from src.core.models.enums import ProcessorType
from src.core.exceptions import ProcessingError
from src.core.models.response_factory import ResponseFactory
from src.core.config import Config
from src.processors.video_processor import VideoProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.processors.pdf_processor import PDFProcessor
from src.utils.performance_tracker import get_performance_tracker
from src.processors.cacheable_processor import CacheableProcessor
from utils.performance_tracker import PerformanceTracker

# TypeVar für den Rückgabetyp von Tasks definieren
T = TypeVar('T')

class SessionProcessingResult:
    """
    Ergebnisstruktur für die Session-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        web_text: str,
        video_transcript: str,
        attachments_text: str,
        markdown_content: str,
        markdown_file: str,
        process_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        self.web_text = web_text
        self.video_transcript = video_transcript
        self.attachments_text = attachments_text
        self.markdown_content = markdown_content
        self.markdown_file = markdown_file
        self.process_id = process_id
        self.context = context
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "web_text": self.web_text,
            "video_transcript": self.video_transcript,
            "attachments_text": self.attachments_text,
            "markdown_content": self.markdown_content,
            "markdown_file": self.markdown_file,
            "process_id": self.process_id,
            "context": self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionProcessingResult':
        """Erstellt ein SessionProcessingResult aus einem Dictionary."""
        return cls(
            web_text=data.get("web_text", ""),
            video_transcript=data.get("video_transcript", ""),
            attachments_text=data.get("attachments_text", ""),
            markdown_content=data.get("markdown_content", ""),
            markdown_file=data.get("markdown_file", ""),
            process_id=data.get("process_id"),
            context=data.get("context")
        )

class SessionProcessor(CacheableProcessor[SessionProcessingResult]):
    """
    Session-Processor für die Verarbeitung von einzelnen Sessions von Events.
    
    Funktionalität:
    -------------
    - Scraping der Session-Webseite
    - Extraktion von Metadaten (Titel, Sprecher, Datum, etc.)
    - Download und Verarbeitung von Videos
    - Download und Verarbeitung von Anhängen
    - Generierung einer Markdown-Zusammenfassung
    - Übersetzung in die Zielsprache
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "session_cache"
    
    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den Session-Processor.
        
        Args:
            resource_calculator: Berechnet die Ressourcennutzung während der Verarbeitung
            process_id: Optionale eindeutige ID für diesen Verarbeitungsprozess
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            session_config: Dict[str, Any] = processor_config.get('session', {})
            
            # Basis-Verzeichnis für Session-Dateien
            self.base_dir: Path = Path(session_config.get('base_dir', 'sessions'))
            if not self.base_dir.exists():
                self.base_dir.mkdir(parents=True)
                
            # Initialisiere Sub-Prozessoren
            self.video_processor: VideoProcessor = VideoProcessor(resource_calculator, process_id)
            self.transformer_processor: TransformerProcessor = TransformerProcessor(resource_calculator, process_id)
            self.pdf_processor: PDFProcessor = PDFProcessor(resource_calculator, process_id)
            
            # Konfigurationswerte mit Typ-Annotationen
            max_concurrent_tasks: int = session_config.get('max_concurrent_tasks', 5)
            self._processing_semaphore = asyncio.Semaphore(max_concurrent_tasks)
            
            # Konfiguration für den Prozessor
            self.processor_type = ProcessorType.SESSION
            self.default_target_dir = Path("output") / "sessions"
            
            self.logger.debug("Session Processor initialisiert",
                            base_dir=str(self.base_dir),
                            temp_dir=str(self.temp_dir),
                            max_concurrent_tasks=max_concurrent_tasks)
                            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des SessionProcessors",
                            error=e,
                            traceback=traceback.format_exc())
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    async def _fetch_session_page(self, url: str) -> str:
        """
        Ruft die Session-Seite ab und extrahiert den HTML-Body.
        
        Args:
            url: URL der Session-Seite
            
        Returns:
            Extrahierter Text der Seite
        """
        start_time = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('fetch_session_page', 'session') if tracker else nullcontext():
                self.logger.info(f"Rufe Session-Seite ab: {url}")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response: requests.Response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Parse HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extrahiere Text
                text = soup.get_text(separator='\n', strip=True)
                
                processing_time = time.time() - start_time
                self.logger.debug("Session-Seite verarbeitet",
                                processing_time=processing_time,
                                text_length=len(text))
                
                return text
            
        except Exception as e:
            self.logger.error("Fehler beim Abrufen der Session-Seite", 
                             error=e,
                             url=url,
                             traceback=traceback.format_exc())
            raise ProcessingError(f"Fehler beim Abrufen der Session-Seite: {str(e)}")

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
            with tracker.measure_operation('process_video', 'session') if tracker else nullcontext():
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
                
                processing_time = time.time() - start_time
                self.logger.debug("Video verarbeitet",
                                processing_time=processing_time,
                                transcription_length=len(transcription))
                
                return transcription, result.process.llm_info
                
        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung", 
                             error=e,
                             video_url=video_url,
                             traceback=traceback.format_exc())
            raise ProcessingError(f"Fehler bei der Video-Verarbeitung: {str(e)}")

    async def _generate_markdown(
        self,
        web_text: str,
        video_transcript: str,
        attachments_text: str,
        session_data: SessionInput,
        target_dir: Path,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Path, str, Optional[LLMInfo]]:
        """
        Generiert die Markdown-Datei mit allen Informationen.
        
        Args:
            web_text: Extrahierter Text der Session-Seite
            video_transcript: Transkription des Videos
            attachments_text: Extrahierter Text der Anhänge
            session_data: Session-Metadaten
            target_dir: Zielverzeichnis für die erzeugte Markdown-Datei
            context: Optionaler zusätzlicher Kontext für das Template
            
        Returns:
            Tuple aus Markdown-Datei-Pfad, generiertem Markdown-Text und LLM-Info
        """
        start_time: float = time.time()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            with tracker.measure_operation('generate_markdown', 'session') if tracker else nullcontext():
                self.logger.info("Generiere Markdown")
                
                # Template-Transformation in Quellsprache durchführen
                result: TransformerResponse = self.transformer_processor.transformByTemplate(
                    source_text="Webtext:\n" + web_text + "\n\n-----\n\nVideotranscript:\n" + video_transcript + "\n\n-----\n\nAttachments:\n" + attachments_text,
                    source_language=session_data.source_language, 
                    target_language=session_data.target_language,  
                    template=session_data.template,
                    context=context,
                    use_cache=False
                )
                
                # Markdown-Inhalt extrahieren
                markdown_content: str = ""
                
                if result.data and hasattr(result.data, 'output') and hasattr(result.data.output, 'text'):
                    markdown_content = result.data.output.text
                else:
                    self.logger.warning(
                        "Unerwartete Struktur der Transformer-Antwort, verwende leeren Markdown-Inhalt",
                        data_type=type(result.data).__name__ if result.data else "None"
                    )
                
                # Anhänge hinzufügen falls vorhanden
                if session_data.attachments_url:
                    markdown_content += "\n## Presentation:\n" 
                    markdown_content += f"[{(session_data.attachments_url.split('/')[-1])}]({session_data.attachments_url})\n\n"
                    # Einzelne Bilder aus der Gallery einfügen, falls vorhanden
                    if context and "gallery" in context and context["gallery"]:
                        # Bilder einzeln einfügen
                        for image_path in context["gallery"]:
                            # Normalisierten Pfad erstellen (falls nicht bereits normalisiert)
                            normalized_path = image_path.replace("\\", "/")
                            # Bild im Markdown-Format einfügen
                            markdown_content += f"![Vorschaubild|300]({normalized_path}) "
                
                # Markdown-Datei im Session-Verzeichnis speichern
                markdown_file: Path = target_dir / session_data.filename
                markdown_file.write_text(markdown_content, encoding='utf-8')
                
                processing_time = time.time() - start_time
                self.logger.debug("Markdown generiert",
                                processing_time=processing_time,
                                markdown_length=len(markdown_content))
                    
                return markdown_file, markdown_content, result.process.llm_info
                
        except Exception as e:
            self.logger.error("Fehler bei der Markdown-Generierung", 
                             error=e,
                             session=session_data.session,
                             traceback=traceback.format_exc())
            raise ProcessingError(f"Markdown-Generierung fehlgeschlagen: {str(e)}")

    async def _process_attachments(
        self,
        attachments_url: str,
        session_data: SessionInput,
        target_dir: Path
    ) -> Tuple[List[str], str, Optional[LLMInfo]]:
        """
        Verarbeitet die Anhänge einer Session.
        
        Args:
            attachments_url: URL zu den Anhängen
            session_data: Session-Metadaten
            target_dir: Zielverzeichnis für die verarbeiteten Dateien
            
        Returns:
            Tuple aus (Liste der Bildpfade, extrahierter Text, LLM-Info)
            
        Raises:
            ProcessingError: Bei Fehlern in der Verarbeitung
        """
        start_time = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('process_attachments', 'session') if tracker else nullcontext():
                self.logger.info(f"Verarbeite Anhänge: {attachments_url}")
                
                # Erstelle Verzeichnis für Assets
                assets_dir = target_dir / "assets"
                if not assets_dir.exists():
                    assets_dir.mkdir(parents=True)
                    
                # Verarbeite PDF direkt von der URL für Vorschaubilder und Textextraktion
                pdf_result: PDFResponse = await self.pdf_processor.process(
                    file_path=attachments_url,
                    extraction_method='preview_and_native'
                )
                
                if pdf_result.error:
                    raise ProcessingError(
                        f"Fehler bei der PDF-Vorschau und -Textextraktion: {pdf_result.error.message}",
                        details=pdf_result.error.details
                    )
                
                # Extrahiere Vorschaubilder
                gallery_paths: List[str] = []
                if pdf_result.data and pdf_result.data.metadata.preview_paths:
                    self.logger.info(f"Extrahiere Vorschaubilder aus Metadaten: {len(pdf_result.data.metadata.preview_paths)} Bilder gefunden")
                    
                    # Stelle sicher, dass das Assets-Verzeichnis existiert
                    if not assets_dir.exists():
                        assets_dir.mkdir(parents=True)
                    
                    # VERBESSERTE VERSION DES KOPIERENS MIT VERIFIKATION
                    successful_copies: int = 0
                    failed_copies: int = 0
                    missing_copies: List[Tuple[str, str]] = []
                    source_paths: List[str] = pdf_result.data.metadata.preview_paths
                    
                    self.logger.info(f"Starte Kopieren von {len(source_paths)} Bildern")
                    
                    # Erste Runde: Kopiere jedes Bild
                    for index, source_path in enumerate(source_paths):
                        file_name: str = ""  # Initialisierung, um Linter-Fehler zu vermeiden
                        try:
                            # Dateiname ohne Pfad extrahieren
                            file_name = Path(source_path).name
                            
                            # Zielpath im assets-Verzeichnis
                            target_path: Path = assets_dir / file_name
                            
                            # Datei kopieren
                            shutil.copy2(source_path, target_path)
                            
                            # Verifikation der Kopie
                            if target_path.exists():
                                # Normalisierter Pfad für die Gallery
                                normalized_path = f"assets/{file_name}"
                                gallery_paths.append(normalized_path)
                                successful_copies += 1
                                self.logger.debug(f"Vorschaubild kopiert ({index+1}/{len(source_paths)}): {source_path} -> {target_path}")
                            else:
                                self.logger.warning(f"Bild wurde kopiert, ist aber nicht im Zielverzeichnis: {target_path}")
                                missing_copies.append((source_path, file_name))
                                failed_copies += 1
                                
                        except Exception as e:
                            self.logger.warning(f"Fehler beim Kopieren des Vorschaubilds {source_path}: {str(e)}")
                            missing_copies.append((source_path, file_name))
                            failed_copies += 1
                    
                    # Zweite Runde: Versuche fehlende Bilder erneut zu kopieren
                    if missing_copies:
                        self.logger.warning(f"{failed_copies} Bilder konnten nicht kopiert werden. Starte zweiten Versuch...")
                        
                        for source_path, file_name in missing_copies:
                            try:
                                # Kurze Pause vor dem Wiederholungsversuch
                                time.sleep(0.1)  
                                
                                # Zielpath im assets-Verzeichnis
                                target_path: Path = assets_dir / file_name
                                
                                # Datei kopieren (zweiter Versuch)
                                shutil.copy2(source_path, target_path)
                                
                                # Erneute Verifikation
                                if target_path.exists():
                                    normalized_path = f"assets/{file_name}"
                                    gallery_paths.append(normalized_path)
                                    successful_copies += 1
                                    failed_copies -= 1
                                    self.logger.info(f"Zweiter Versuch erfolgreich für: {file_name}")
                                else:
                                    self.logger.error(f"Auch zweiter Kopierversuch gescheitert für: {file_name}")
                            except Exception as e:
                                self.logger.error(f"Zweiter Kopierversuch fehlgeschlagen für {file_name}: {str(e)}")
                    
                    # Finale Verifizierung: Liste alle Dateien im Zielverzeichnis auf
                    actual_files_in_assets: List[Path] = list(assets_dir.glob('*.*'))
                    actual_count: int = len(actual_files_in_assets)
                    
                    # Logge die Zusammenfassung
                    self.logger.info(f"Bildkopiervorgang abgeschlossen: {successful_copies} erfolgreich, " 
                                   f"{failed_copies} fehlgeschlagen. "
                                   f"{actual_count} Dateien im Zielverzeichnis gefunden.")
                    
                    # Logge die generierten Pfade
                    self.logger.info(f"Generierte Gallery-Pfade: {len(gallery_paths)} Einträge")
                
                # Extrahiere Text
                extracted_text = pdf_result.data.extracted_text if pdf_result.data else ""
                
                # Kombiniere LLM-Info
                combined_llm_info = LLMInfo(model="pdf-processing", purpose="pdf-processing")
                if pdf_result.process and pdf_result.process.llm_info:
                    combined_llm_info.add_request(pdf_result.process.llm_info.requests)
                
                processing_time = time.time() - start_time
                self.logger.debug("Anhänge verarbeitet",
                                processing_time=processing_time,
                                gallery_count=len(gallery_paths),
                                text_length=len(extracted_text or ""))
                
                return gallery_paths, extracted_text or "", combined_llm_info
                
        except Exception as e:
            self.logger.error("Fehler bei der Anhang-Verarbeitung", 
                             error=e,
                             url=attachments_url,
                             traceback=traceback.format_exc())
            raise ProcessingError(
                f"Fehler bei der Anhang-Verarbeitung: {str(e)}",
                details={
                    "url": attachments_url,
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )

    async def process_session(
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
        template: str = "Session",
        use_cache: bool = True
    ) -> SessionResponse:
        """
        Verarbeitet eine Session mit allen zugehörigen Medien.
        
        Args:
            event: Name der Veranstaltung
            session: Name der Session
            url: URL zur Session-Seite
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
            template: Optional, Name des Templates für die Markdown-Generierung (Standard: Session)
            use_cache: Optional, ob die Ergebnisse zwischengespeichert werden sollen
            
        Returns:
            SessionResponse mit Metadaten und erzeugtem Markdown
        """
        # Hol den Performance-Tracker
        tracker = get_performance_tracker()
        
        try:
            # Beginn der Zeitmessung für die Gesamtverarbeitung
            with tracker.measure_operation('process_session', 'session') if tracker else nullcontext():
                # Eingabedaten validieren
                input_data = SessionInput(
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
                    template=template
                )
                
                # LLM-Tracking initialisieren
                llm_info = LLMInfo(model="session-processor", purpose="process-session")
                
                self.logger.info(f"Starte Verarbeitung von Session: {session}")
                
                
                # Erstelle formatierten Session-Verzeichnisnamen mit Startzeit
                session_dir_name = f"{Path(filename).stem}"
                
                # Zielverzeichnisstruktur erstellen:
                # sessions/[session]/[track]/[time-session_dir]
                target_dir: Path = self.base_dir / event / track / session_dir_name
                if not target_dir.exists():
                    target_dir.mkdir(parents=True)
                
                # 1. Session-Seite abrufen
                web_text = await self._fetch_session_page(url)
                
                # 2. Video verarbeiten falls vorhanden
                video_transcript = ""
                if video_url:
                    video_transcript, video_llm_info = await self._process_video(
                        video_url=video_url,
                        source_language=source_language,
                        target_language=source_language, # transcript bleibt aus performancegründen immer in originalsprache
                        use_cache=use_cache
                    )
                    
                    # LLM-Tracking: Video-Prozessor LLM-Nutzung hinzufügen
                    if video_llm_info:
                        llm_info.requests.extend(video_llm_info.requests)
                
                # 3. Anhänge verarbeiten falls vorhanden
                attachment_paths = []
                attachments_text = ""
                attachment_llm_info = None
                
                if attachments_url:
                    attachment_paths, attachments_text, attachment_llm_info = await self._process_attachments(
                        attachments_url=attachments_url,
                        session_data=input_data,
                        target_dir=target_dir
                    )
                    
                    # LLM-Tracking: PDF-Prozessor LLM-Nutzung hinzufügen
                    if attachment_llm_info:
                        llm_info.requests.extend(attachment_llm_info.requests)
                
                # 4. Markdown generieren
                template_context = {
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
                    "attachment_paths": attachment_paths,
                    "gallery": attachment_paths  # Für die Bildergalerie
                }

                markdown_file, markdown_content, transformer_llm_info = await self._generate_markdown(
                    web_text=web_text,
                    video_transcript=video_transcript,
                    attachments_text=attachments_text,
                    session_data=input_data,
                    target_dir=target_dir,
                    context=template_context
                )
                
                # LLM-Tracking: Transformer-Prozessor LLM-Nutzung hinzufügen
                if transformer_llm_info:
                    llm_info.requests.extend(transformer_llm_info.requests)
                
                # 5. Erstelle Output-Daten
                output_data = SessionOutput(
                    web_text=web_text,
                    video_transcript=video_transcript,
                    attachments_text=attachments_text,
                    context=template_context,
                    markdown_file=str(markdown_file),
                    markdown_content=markdown_content,
                )
                
                # 6. Ergebnis im Cache speichern (wenn aktiviert)
                if use_cache and self.is_cache_enabled():
                    result = SessionProcessingResult(
                        web_text=web_text,
                        video_transcript=video_transcript,
                        attachments_text=attachments_text,
                        markdown_content=markdown_content,
                        markdown_file=str(markdown_file),
                        process_id=self.process_id,
                        context=template_context
                    )
                    
                    # Im Cache speichern
                    cache_key = self._create_cache_key(input_data)
                    self.save_to_cache(
                        cache_key=cache_key,
                        result=result
                    )
                    self.logger.debug(f"Session-Ergebnis im Cache gespeichert: {cache_key}")
                
                # 7. Response erstellen
                return ResponseFactory.create_response(
                    processor_name=ProcessorType.SESSION.value,
                    result=SessionData(
                        input=input_data,
                        output=output_data
                    ),
                    request_info={
                        "event": event,
                        "session": session,
                        "url": url,
                        "track": track
                    },
                    response_class=SessionResponse,
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
            self.logger.error("Fehler bei der Session-Verarbeitung", 
                             error=e,
                             session=session,
                             traceback=traceback.format_exc())
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.SESSION.value,
                result=None,
                request_info={
                    "event": event,
                    "session": session,
                    "url": url,
                    "track": track
                },
                response_class=SessionResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def process_many_sessions(
        self,
        sessions: List[Dict[str, Any]]
    ) -> BatchSessionResponse:
        """
        Verarbeitet mehrere Sessions sequentiell.
        
        Args:
            sessions: Liste von Session-Daten mit denselben Parametern wie process_session
            
        Returns:
            BatchSessionResponse: Ergebnis der Batch-Verarbeitung
        """
        start_time = time.time()
        
        try:
            # Initialisiere Listen für Ergebnisse und Fehler
            successful_outputs: List[SessionOutput] = []
            errors: List[Dict[str, Any]] = []
            llm_infos: List[LLMInfo] = []
            
            # Verarbeite Sessions sequentiell
            for i, session_data in enumerate(sessions):
                try:
                    # Verarbeite einzelne Session
                    result = await self.process_session(
                        event=session_data.get("event", ""),
                        session=session_data.get("session", ""),
                        url=session_data.get("url", ""),
                        filename=session_data.get("filename", ""),
                        track=session_data.get("track", ""),
                        day=session_data.get("day"),
                        starttime=session_data.get("starttime"),
                        endtime=session_data.get("endtime"),
                        speakers=session_data.get("speakers", []),
                        video_url=session_data.get("video_url"),
                        attachments_url=session_data.get("attachments_url"),
                        source_language=session_data.get("source_language", "en"),
                        target_language=session_data.get("target_language", "de"),
                        template=session_data.get("template", "Session")
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
                        "session": session_data.get("session", "unknown"),
                        "error": str(e)
                    })
                    self.logger.error(
                        f"Fehler bei der Verarbeitung von Session {i}",
                        error=e,
                        session=session_data.get("session", "unknown")
                    )
            
            # Erstelle BatchSessionOutput
            batch_output = BatchSessionOutput(
                results=successful_outputs,
                summary={
                    "total_sessions": len(sessions),
                    "successful": len(successful_outputs),
                    "failed": len(errors),
                    "errors": errors,
                    "processing_time": time.time() - start_time
                }
            )
            
            # Erstelle BatchSessionData
            batch_data = BatchSessionData(
                input=BatchSessionInput(sessions=sessions),
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
                processor_name=ProcessorType.SESSION.value,
                result=batch_data,
                request_info={
                    "session_count": len(sessions),
                    "successful": len(successful_outputs),
                    "failed": len(errors)
                },
                response_class=BatchSessionResponse,
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
                processor_name=ProcessorType.SESSION.value,
                result=None,
                request_info={
                    "session_count": len(sessions)
                },
                response_class=BatchSessionResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    async def process_sessions_async(
        self,
        sessions: List[Dict[str, Any]],
        webhook_url: str,
        webhook_headers: Optional[Dict[str, str]] = None,
        include_markdown: bool = True,
        include_metadata: bool = True,
        batch_id: Optional[str] = None
    ) -> BatchSessionResponse:
        """
        Verarbeitet mehrere Sessions asynchron und sendet Webhook-Callbacks nach Abschluss jeder Session.
        
        Verwendet die MongoDB-basierte Job-Verwaltung für die asynchrone Verarbeitung.
        
        Args:
            sessions: Liste von Session-Daten mit denselben Parametern wie process_session
            webhook_url: URL für den Webhook-Callback
            webhook_headers: Optional, HTTP-Header für den Webhook
            include_markdown: Optional, ob der Markdown-Inhalt im Webhook enthalten sein soll
            include_metadata: Optional, ob die Metadaten im Webhook enthalten sein soll
            batch_id: Optional, eine eindeutige ID für den Batch
            
        Returns:
            BatchSessionResponse: Eine sofortige Antwort, dass die Sessions zur Verarbeitung angenommen wurden
        """
        try:
            # Erstelle Webhook-Konfiguration
            webhook_config = WebhookConfig(
                url=webhook_url,
                headers=webhook_headers or {},
                include_markdown=include_markdown,
                include_metadata=include_metadata,
                session_id=batch_id or str(uuid.uuid4())
            )
            
            # Erstelle Eingabedaten
            input_data = AsyncBatchSessionInput(
                sessions=sessions,
                webhook=webhook_config
            )
            
            # Starte die asynchrone Verarbeitung in einem separaten Task
            # Speichere die Task-Referenz, damit sie nicht vom Garbage Collector entfernt wird
            processing_task = asyncio.create_task(self._process_many_sessions_async_task(input_data))
            
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
                processor_name=ProcessorType.SESSION.value,
                result=BatchSessionData(
                    input=BatchSessionInput(sessions=sessions),
                    output=BatchSessionOutput(
                        results=[],
                        summary={
                            "total_sessions": len(sessions),
                            "status": "accepted",
                            "batch_id": webhook_config.session_id,
                            "webhook_url": webhook_url,
                            "async_processing": True,
                            "processing_type": "mongodb"
                        }
                    )
                ),
                request_info={
                    "session_count": len(sessions),
                    "webhook_url": webhook_url,
                    "batch_id": webhook_config.session_id,
                    "async_processing": True,
                    "processing_type": "mongodb"
                },
                response_class=BatchSessionResponse,
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
            self.logger.error(f"Fehler bei der asynchronen Batch-Session-Verarbeitung: {str(e)}")
            
            return ResponseFactory.create_response(
                processor_name=ProcessorType.SESSION.value,
                result=None,
                request_info={
                    "session_count": len(sessions),
                    "webhook_url": webhook_url,
                    "async_processing": True,
                    "processing_type": "mongodb"
                },
                response_class=BatchSessionResponse,
                error=error_info,
                llm_info=None,
                from_cache=False
            )

    def _create_empty_session_output(self) -> SessionOutput:
        """Erstellt eine leere SessionOutput-Instanz für Fehlerfälle."""
        return SessionOutput(
            web_text="",
            video_transcript="",
            attachments_text="",
            context={},
            markdown_file="",
            markdown_content=""
        )

    async def _process_many_sessions_async_task(self, input_data: AsyncBatchSessionInput) -> None:
        """
        Task für die asynchrone Verarbeitung mehrerer Sessions.
        
        Erstellt Jobs in der MongoDB und startet den Worker-Manager.
        
        Args:
            input_data: Eingabedaten für die Session-Verarbeitung
        """
        from src.core.mongodb import get_job_repository
        from typing import List
        
        self.logger.info(
            "Starte asynchrone Batchverarbeitung über MongoDB",
            session_count=len(input_data.sessions)
        )
        
        # Job-Repository holen
        job_repo = get_job_repository()
        
        # Batch erstellen
        batch_data = {
            "total_jobs": len(input_data.sessions),
            "webhook": input_data.webhook.to_dict() if input_data.webhook else None
        }
        
        batch_id = job_repo.create_batch(batch_data)
        
        # Jobs für jede Session erstellen
        job_ids: List[str] = []
        for session_index, session in enumerate(input_data.sessions):
            # Session-Daten validieren
            session_data = self._validate_session_data(session)
            if not session_data:
                self.logger.warning(
                    f"Ungültige Session-Daten, überspringe Session {session_index}",
                    session_id=session_index
                )
                continue
                
            # Stelle sicher, dass alle notwendigen Parameter vorhanden sind
            # Besonders wichtig: source_language, target_language und template für die Template-Transformation
            if "source_language" not in session_data:
                session_data["source_language"] = "en"
            if "target_language" not in session_data:
                session_data["target_language"] = "de"
            if "template" not in session_data:
                session_data["template"] = "Session"
            
            # Job erstellen
            job_data = {
                "batch_id": batch_id,
                "parameters": session_data,
                "webhook": input_data.webhook.to_dict() if input_data.webhook else None
            }
            
            job_id = job_repo.create_job(job_data)
            job_ids.append(job_id)
            
            self.logger.info(
                f"Job erstellt für Session {session_index+1}/{len(input_data.sessions)}: {session_data.get('session', 'Unbekannt')}",
                job_id=job_id,
                session_id=session_index
            )
        
        self.logger.info(
            f"Batch-Job erstellt mit ID {batch_id}, {len(job_ids)} Sessions in die Queue eingereiht"
        )
        
        return

    def _validate_session_data(self, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validiert die Session-Daten und gibt ein bereinigtes Dictionary zurück.
        
        Args:
            session: Die zu validierenden Session-Daten
            
        Returns:
            Optional[Dict[str, Any]]: Die validierten Daten oder None, wenn die Daten ungültig sind
        """
        if not session:
            self.logger.warning("Session-Daten sind leer")
            return None
        
        # Prüfe, ob mindestens Pflichtfelder vorhanden sind
        required_fields = ["event", "session"]
        for field in required_fields:
            if field not in session or not session[field]:
                self.logger.warning(f"Pflichtfeld '{field}' fehlt in Session-Daten oder ist leer")
                return None
        
        # Stelle sicher, dass alle notwendigen Parameter vorhanden sind
        # Besonders wichtig: source_language, target_language und template für die Template-Transformation
        if "source_language" not in session:
            session["source_language"] = "en"
        if "target_language" not in session:
            session["target_language"] = "de"
        if "template" not in session:
            session["template"] = "Session"
        
        return session

    def _create_cache_key(self, session_input: SessionInput) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf den Session-Daten.
        
        Args:
            session_input: Die Eingabedaten für die Session
            
        Returns:
            str: Ein eindeutiger Cache-Schlüssel
        """
        # Basis-Informationen extrahieren
        base_key = {
            "event": session_input.event,
            "session": session_input.session,
            "url": session_input.url,
            "track": session_input.track,
            "target_language": session_input.target_language,
            "template": session_input.template
        }
        
        # Optionale Video-URL hinzufügen
        if session_input.video_url:
            base_key["video_url"] = session_input.video_url
        
        # Optionale Anhänge-URL hinzufügen
        if session_input.attachments_url:
            base_key["attachments_url"] = session_input.attachments_url
        
        # JSON-String erstellen und hashen
        key_string = json.dumps(base_key, sort_keys=True)
        
        self.logger.debug(f"Cache-Schlüssel erstellt: {key_string}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(key_string)

    def serialize_for_cache(self, result: SessionProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das SessionProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das SessionProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "processed_at": datetime.now().isoformat(),
            # Da SessionProcessingResult kein metadata-Attribut hat, können wir hier keine weiteren Metadaten hinzufügen
            "event": "",
            "session": "",
            "track": "",
            "target_language": ""
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> SessionProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein SessionProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            SessionProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        return SessionProcessingResult.from_dict(result_data)

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Session-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Indizes für häufige Suchfelder
            index_fields = [
                ("event", 1),
                ("session", 1),
                ("track", 1),
                ("processed_at", 1),
                ("target_language", 1)
            ]
            
            # Indizes erstellen, wenn sie noch nicht existieren
            for field, direction in index_fields:
                index_name = f"{field}_{direction}"
                if index_name not in index_info:
                    collection.create_index([(field, direction)])
                    self.logger.debug(f"{field}-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")
