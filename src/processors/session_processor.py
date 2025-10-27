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
import zipfile
import base64
import io
from pymongo.collection import Collection
from pymongo.cursor import Cursor

from src.processors.pdf_processor import PDFResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.video import VideoResponse
from src.core.models.session import (
    SessionInput, SessionOutput, SessionData, SessionResponse, BatchSessionResponse, BatchSessionOutput, BatchSessionData, BatchSessionInput,
    WebhookConfig, AsyncBatchSessionInput
)
from src.core.models.base import (
     ErrorInfo, ProcessInfo
)
from src.core.models.enums import ProcessorType, ProcessingStatus
from src.core.exceptions import ProcessingError
from src.core.config import Config
from src.processors.video_processor import VideoProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.processors.pdf_processor import PDFProcessor
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker
from src.processors.cacheable_processor import CacheableProcessor
from src.core.resource_tracking import ResourceCalculator

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
        attachment_paths: List[str],
        page_texts: List[str],
        target_dir: str,
        markdown_content: str,
        markdown_file: str,
        structured_data: Dict[str, Any],
        process_id: Optional[str] = None,
        input_data: Optional[SessionInput] = None
    ):
        self.web_text = web_text
        self.video_transcript = video_transcript
        self.attachment_paths = attachment_paths
        self.page_texts = page_texts
        self.target_dir = target_dir
        self.markdown_content = markdown_content
        self.markdown_file = markdown_file
        self.process_id = process_id
        self.input_data = input_data
        self.structured_data = structured_data
        
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.markdown_content else ProcessingStatus.ERROR
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "web_text": self.web_text,
            "video_transcript": self.video_transcript,
            "attachment_paths": self.attachment_paths,
            "page_texts": self.page_texts,
            "target_dir": self.target_dir,
            "markdown_content": self.markdown_content,
            "markdown_file": self.markdown_file,
            "process_id": self.process_id,
            "input_data": self.input_data.to_dict() if self.input_data else {},
            "structured_data": self.structured_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionProcessingResult':
        """Erstellt ein SessionProcessingResult aus einem Dictionary."""
        return cls(
            web_text=data.get("web_text", ""),
            video_transcript=data.get("video_transcript", ""),
            attachment_paths=data.get("attachment_paths", []),
            page_texts=data.get("page_texts", []),
            target_dir=data.get("target_dir", ""),
            markdown_content=data.get("markdown_content", ""),
            markdown_file=data.get("markdown_file", ""),
            process_id=data.get("process_id"),
            input_data=SessionInput.from_dict(data.get("input_data", {})),
            structured_data=data.get("structured_data", {})
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
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None) -> None:
        """
        Initialisiert den Session-Processor.
        
        Args:
            resource_calculator: Berechnet die Ressourcennutzung während der Verarbeitung
            process_id: Optionale eindeutige ID für diesen Verarbeitungsprozess
            parent_process_info: Optionale Prozessinformationen des übergeordneten Prozessors
        """
        # Basis-Initialisierung mit dem BaseProcessor
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            session_config: Dict[str, Any] = processor_config.get('session', {})
            
            # Basis-Verzeichnis für Session-Dateien
            self.base_dir: Path = Path(session_config.get('base_dir', 'sessions'))
            if not self.base_dir.exists():
                self.base_dir.mkdir(parents=True)
                
            # Initialisiere Sub-Prozessoren mit parent_process_info für hierarchisches Tracking
            self.video_processor: VideoProcessor = VideoProcessor(
                resource_calculator=self.resource_calculator, 
                process_id=process_id,
                parent_process_info=self.process_info
            )
            self.transformer_processor: TransformerProcessor = TransformerProcessor(
                resource_calculator=self.resource_calculator, 
                process_id=process_id,
                parent_process_info=self.process_info
            )
            self.pdf_processor: PDFProcessor = PDFProcessor(
                resource_calculator=self.resource_calculator, 
                process_id=process_id,
                parent_process_info=self.process_info
            )
            
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

    async def _process_video(self, video_url: str, source_language: str, target_language: str, use_cache: bool = True) -> str:
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
                
                return transcription
                
        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung", 
                             error=e,
                             video_url=video_url,
                             traceback=traceback.format_exc())
            # NICHT-FATAL: Wenn Video scheitert, geben wir leeres Transkript zurück
            # und setzen die Session-Verarbeitung fort (web_text, PDFs, Markdown)
            self.logger.warning("Video-Verarbeitung fehlgeschlagen - fahre ohne Transkript fort")
            return ""  # Leeres Transkript statt Exception

    def _replace_video_placeholder(self, markdown_content: str, video_url: Optional[str]) -> str:
        """
        Ersetzt den {videoplayer} Platzhalter durch passenden Markdown-Code.
        
        Args:
            markdown_content: Der Markdown-Inhalt mit Platzhaltern
            video_url: Die Video-URL (kann None sein)
            
        Returns:
            str: Markdown-Inhalt mit ersetztem Video-Platzhalter
        """
        if not video_url:
            # Wenn keine Video-URL vorhanden ist, entferne den Platzhalter
            return markdown_content.replace("{videoplayer}", "").replace("{{video_url}}", "")
        
        # Prüfe, ob es sich um eine Vimeo-URL handelt
        is_vimeo = "vimeo.com" in video_url or "player.vimeo.com" in video_url
        
        if is_vimeo:
            # Für Vimeo-Videos: iframe verwenden
            video_markdown = f'<iframe src="{video_url}" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        else:
            # Für normale Videos: HTML5 video Element verwenden
            video_markdown = f'<video src="{video_url}" controls></video>'
        
        # Ersetze beide Platzhalter-Varianten
        markdown_content = markdown_content.replace("{videoplayer}", video_markdown)
        markdown_content = markdown_content.replace("{{video_url}}", video_markdown)
        
        self.logger.debug(f"Video-Platzhalter ersetzt",
                         video_url=video_url,
                         is_vimeo=is_vimeo,
                         video_markdown=video_markdown)
        
        return markdown_content

    def _create_session_archive(
        self,
        markdown_content: str,
        markdown_file_path: str,
        attachment_paths: List[str],
        asset_dir: str,
        session_data: SessionInput
    ) -> Tuple[str, str]:
        """
        Erstellt ein ZIP-Archiv mit der originalen Verzeichnisstruktur.
        
        Args:
            markdown_content: Der Markdown-Inhalt
            markdown_file_path: Vollständiger Pfad zur Markdown-Datei
            attachment_paths: Liste der Anhang-Pfade (relativ)
            asset_dir: Verzeichnis mit den Asset-Dateien
            session_data: Session-Eingabedaten
            
        Returns:
            Tuple aus (Base64-kodiertes ZIP, ZIP-Dateiname)
        """
        try:
            self.logger.info("Erstelle ZIP-Archiv für Session mit originaler Struktur", 
                           session=session_data.session,
                           attachment_count=len(attachment_paths),
                           markdown_file=markdown_file_path,
                           asset_dir=asset_dir)
            
            # ZIP-Dateiname generieren
            sanitized_session_name = self._sanitize_filename(session_data.session)
            zip_filename = f"{sanitized_session_name}.zip"
            
            # In-Memory ZIP erstellen
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # 1. Markdown-Datei mit originaler Pfadstruktur hinzufügen
                # markdown_file_path ist bereits relativ wie "sessions/2024 SFSCON/en/Data Spaces/session.md"
                zip_file.writestr(markdown_file_path, markdown_content.encode('utf-8'))
                self.logger.debug(f"Markdown-Datei zum ZIP hinzugefügt: {markdown_file_path}")
                
                # 2. Alle Asset-Dateien mit originaler Pfadstruktur hinzufügen
                successful_images = 0
                failed_images = 0
                
                for attachment_path in attachment_paths:
                    try:
                        # Vollständigen lokalen Pfad konstruieren
                        full_local_path = self.base_dir / attachment_path
                        
                        if full_local_path.exists():
                            # Asset mit originalem Pfad zum ZIP hinzufügen
                            # attachment_path ist bereits korrekt wie "sessions/2024 SFSCON/assets/session_name/image.png"
                            zip_file.write(str(full_local_path), attachment_path)
                            successful_images += 1
                            self.logger.debug(f"Asset zum ZIP hinzugefügt: {attachment_path}")
                        else:
                            self.logger.warning(f"Asset nicht gefunden: {full_local_path}")
                            failed_images += 1
                            
                    except Exception as e:
                        self.logger.warning(f"Fehler beim Hinzufügen des Assets {attachment_path}: {str(e)}")
                        failed_images += 1
                
                # 3. README mit Nutzungshinweisen hinzufügen (in Root des ZIP)
                readme_content = self._create_archive_readme(session_data, successful_images)
                zip_file.writestr("README.md", readme_content.encode('utf-8'))
            
            # ZIP-Daten als Base64 kodieren
            zip_buffer.seek(0)
            zip_data = zip_buffer.getvalue()
            base64_zip = base64.b64encode(zip_data).decode('utf-8')
            
            self.logger.info(f"ZIP-Archiv mit originaler Struktur erstellt: {len(zip_data)} Bytes, "
                           f"{successful_images} Assets erfolgreich, {failed_images} fehlgeschlagen")
            
            return base64_zip, zip_filename
            
        except Exception as e:
            self.logger.error("Fehler beim Erstellen des ZIP-Archives", 
                             error=e,
                             session=session_data.session,
                             traceback=traceback.format_exc())
            raise ProcessingError(f"ZIP-Archiv-Erstellung fehlgeschlagen: {str(e)}")



    def _create_archive_readme(self, session_data: SessionInput, image_count: int) -> str:
        """
        Erstellt eine README-Datei für das ZIP-Archiv.
        
        Args:
            session_data: Session-Eingabedaten
            image_count: Anzahl der enthaltenen Bilder
            
        Returns:
            README-Inhalt als String
        """
        return f"""# {session_data.session}

## Event
{session_data.event}

## Track
{session_data.track}

## Archiv-Inhalt

Dieses Archiv enthält die komplette Verzeichnisstruktur:

```
sessions/
├── {session_data.event}/
│   ├── assets/
│   │   └── {Path(session_data.filename).stem}/
│   │       └── [{image_count} Anhang-Bilder]
│   └── {session_data.target_language.upper()}/
│       └── {session_data.track}/
│           └── {session_data.filename}
└── README.md (diese Datei)
```

## Nutzung

1. Entpacken Sie das gesamte Archiv in ein Verzeichnis Ihrer Wahl
2. Die Verzeichnisstruktur wird vollständig wiederhergestellt
3. Die Markdown-Datei enthält korrekte relative Pfade zu den Assets
4. Sie können die Markdown-Datei mit jedem Markdown-fähigen Editor öffnen (z.B. Obsidian, Typora, VS Code)

## Verzeichnisstruktur

Die Struktur wurde so entworfen, dass mehrsprachige Sessions gemeinsame Assets verwenden können:
- **sessions/**: Basis-Verzeichnis für alle Sessions
- **[Event]/assets/**: Gemeinsame Assets für alle Sprachen des Events
- **[Event]/[Sprache]/**: Sprachspezifische Markdown-Dateien
- **[Event]/[Sprache]/[Track]/**: Nach Tracks organisierte Sessions

## Ursprüngliche Daten

- **Session-URL**: {session_data.url}
- **Video-URL**: {session_data.video_url or 'Nicht verfügbar'}
- **Anhänge-URL**: {session_data.attachments_url or 'Nicht verfügbar'}
- **Verarbeitet am**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Sprache**: {session_data.target_language}
- **Template**: {session_data.template}

---
*Generiert vom Secretary Services Session Processor*
"""

    async def _generate_markdown(
        self,
        web_text: str,
        video_transcript: str,
        page_texts: List[str],
        session_data: SessionInput,
        target_dir: Path,
        filename: str,
        template: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Path, str, Any]:
        """
        Generiert die Markdown-Datei mit allen Informationen.
        
        Args:
            web_text: Extrahierter Text der Session-Seite
            video_transcript: Transkription des Videos
            page_texts: Extrahierter Text der Anhänge
            session_data: Session-Metadaten
            target_dir: Zielverzeichnis für die erzeugte Markdown-Datei
            filename: Dateiname für die Markdown-Datei
            template: Name des zu verwendenden Templates
            context: Optionaler zusätzlicher Kontext für das Template
            
        Returns:
            Tuple aus Markdown-Datei-Pfad, generiertem Markdown-Text und strukturierten Daten
        """
        start_time: float = time.time()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            with tracker.measure_operation('generate_markdown', 'session') if tracker else nullcontext():

                # Generiere zusätzliche Feldbeschreibungen für Seitenzusammenfassungen
                #additional_field_descriptions: Dict[str, str] = {}
                slides_descriptions: str = ""
                for i, page_text in enumerate(page_texts, 1):
                    slides_descriptions += f"Description Slide {i}:\n {page_text} \n\n"
                #        f"Description Slide {i}:\n {page_text} \n\n"
                #        f"Bitte auch den entsprechenden Inhalt der Audiotranscription berücksichtigen: \n"
                #        f"{page_text}"
                #    )
                #    field_name = f"attachment_page_{i}_summary"
                #    description = (
                #        f"Können wir den Beschreibenden Text der Folie {i} kurz zusammenfassen? "
                #        f"Bitte auch den entsprechenden Inhalt der Audiotranscription berücksichtigen: \n"
                #        f"{page_text}"
                #    )
                #    additional_field_descriptions[field_name] = description


                self.logger.info("Generiere Markdown")
                
                # Korrigierter Aufruf von transformByTemplate mit korrekten Parameternamen
                combined_text = f"# Webtext:\n{web_text}\n\n-----\n\n# Videotranscript:\n{video_transcript}\n\n-----\n\n# Slidesdescription:\n{slides_descriptions}"
                
                
                # Template-Transformation mit korrekten Parametern
                result: TransformerResponse = self.transformer_processor.transformByTemplate(
                    text=combined_text,
                    template=template,
                    source_language=session_data.source_language, 
                    target_language=session_data.target_language,
                    context=context,
                    # additional_field_descriptions=additional_field_descriptions,
                    use_cache=False
                )
                
                # Markdown-Inhalt extrahieren
                markdown_content: str = ""
                
                # Sicherere Typprüfung und Extraktion von Daten
                if result.data:
                    # Prüfe, ob result.data eine TransformerData-Instanz ist und ob es text enthält
                    if hasattr(result.data, 'text'):
                        markdown_content = result.data.text
                    else:
                        self.logger.warning(
                            "Unerwartete Struktur der Transformer-Antwort, verwende leeren Markdown-Inhalt",
                            data_type=type(result.data).__name__
                        )
                else:
                    self.logger.warning("Keine Daten in der Transformer-Antwort")
                
                # Extrahiere strukturierte Daten aus dem Transformer-Ergebnis
                # Verwende ein leeres Dict als Standardwert
                structured_data: Dict[str, Any] = {}
                
                # Sicherere Extraktion der strukturierten Daten
                if result.data and hasattr(result.data, 'structured_data'):
                    structured_data_raw = result.data.structured_data
                    if structured_data_raw is not None:
                        structured_data = dict(structured_data_raw)

                if(markdown_content.find("{slides}") != -1):
                    # Slides mit Beschreibungen hinzufügen
                    slides: str = ""
                    # Bevorzugt: strukturierte Slides aus structured_data["slides"] nutzen
                    try:
                        if structured_data and isinstance(structured_data.get("slides"), list) and structured_data.get("slides"):
                            slides += "\n## Slides:\n"
                            slides += "|  |  | \n"
                            slides += "| --- | --- | \n"
                            for slide in structured_data.get("slides", []):
                                try:
                                    image_url = str(slide.get("image_url", ""))
                                    normalized_path = image_url.replace("\\", "/")
                                    title = str(slide.get("title", "")).strip()
                                    summary = str(slide.get("summary", "")).replace("\n", " ").strip()
                                    description = summary
                                    if title:
                                        description = f"**{title}** — {summary}" if summary else f"**{title}**"
                                    slides += f"| ![[{normalized_path}\\|300]] | {description} \n"
                                except Exception:
                                    # Wenn ein Slide-Objekt unvollständig ist, einfach überspringen
                                    continue
                        else:
                            self.logger.warning("Keine Slides-Daten gefunden, keine Slides generiert")
                    except Exception:
                        self.logger.warning("Fehler beim Generieren der Slides-Tabelle aus structured_data")

                    markdown_content = markdown_content.replace("{slides}", slides)

                # Video-Platzhalter ersetzen
                markdown_content = self._replace_video_placeholder(markdown_content, session_data.video_url)

                # Sicherstellen, dass der Dateiname keine ungültigen Zeichen enthält
                sanitized_filename = self._sanitize_filename(filename)
                
                # Markdown-Datei im Session-Verzeichnis speichern
                markdown_file: Path = target_dir / sanitized_filename
                markdown_file.write_text(markdown_content, encoding='utf-8')
                
                processing_time = time.time() - start_time
                self.logger.debug("Markdown generiert",
                                processing_time=processing_time,
                                markdown_file=sanitized_filename,
                                markdown_length=len(markdown_content))
                    
                return markdown_file, markdown_content, structured_data
                
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
        target_dir: str,
        use_cache: bool = True
    ) -> Tuple[List[str], List[str], str]:
        """
        Verarbeitet die Anhänge einer Session.
        
        Args:
            attachments_url: URL zu den Anhängen
            session_data: Session-Metadaten
            target_dir: Zielverzeichnis für die verarbeiteten Dateien
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            Tuple aus (Liste der Bildpfade, Liste der Seitentexte, Asset-Verzeichnis)
            
        Raises:
            ProcessingError: Bei Fehlern in der Verarbeitung
        """
        start_time = time.time()
        tracker = get_performance_tracker()
        
        try:
            with tracker.measure_operation('process_attachments', 'session') if tracker else nullcontext():
                self.logger.info(f"Verarbeite Anhänge: {attachments_url}")
                assets_dir: Path = self.base_dir / target_dir

                # Erstelle Verzeichnis für Assets
                if not assets_dir.exists():
                    assets_dir.mkdir(parents=True)
                    
                # Verarbeite PDF direkt von der URL für Vorschaubilder und Textextraktion
                pdf_result: PDFResponse = await self.pdf_processor.process(
                    file_path=attachments_url,
                    extraction_method='preview_and_native',
                    use_cache=use_cache
                )
                
                if pdf_result.error:
                    self.logger.error(f"Fehler bei der PDF-Vorschau und -Textextraktion: {pdf_result.error.message}")
                    return [], [], ""
                
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
                                normalized_path = f"{target_dir}/{file_name}"
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
                                retry_target_path: Path = assets_dir / file_name
                                
                                # Datei kopieren (zweiter Versuch)
                                shutil.copy2(source_path, retry_target_path)
                                
                                # Erneute Verifikation
                                if retry_target_path.exists():
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
                
                # Extrahiere Seitentexte aus text_contents
                page_texts: List[str] = []
                if pdf_result.data and pdf_result.data.metadata.text_contents:
                    # text_contents ist eine Liste von Tupeln (Seitennummer, Text)
                    # Wir extrahieren nur die Texte in der richtigen Reihenfolge
                    page_texts = [text for _, text in sorted(pdf_result.data.metadata.text_contents)]
                    self.logger.info(f"Extrahierte Texte von {len(page_texts)} Seiten")
                
                
                processing_time = time.time() - start_time
                self.logger.debug("Anhänge verarbeitet",
                                processing_time=processing_time,
                                gallery_count=len(gallery_paths),
                                page_count=len(page_texts),
                                asset_dir=str(assets_dir))
                
                return gallery_paths, page_texts, str(assets_dir)
                
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
        video_transcript: Optional[str] = None,
        attachments_url: Optional[str] = None,
        source_language: str = "en",
        target_language: str = "de",
        target: Optional[str] = None,
        template: str = "Session",
        use_cache: bool = True,
        create_archive: bool = True
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
            video_transcript: Optional, bereits vorhandenes Video-Transkript (überspringt Video-Verarbeitung)
            attachments_url: Optional, URL zu Anhängen
            source_language: Optional, Quellsprache (Standard: en)
            target_language: Optional, Zielsprache (Standard: de)
            target: Optional, Zielgruppe der Session
            template: Optional, Name des Templates für die Markdown-Generierung (Standard: Session)
            use_cache: Optional, ob die Ergebnisse zwischengespeichert werden sollen
            create_archive: Optional, ob ein ZIP-Archiv mit Markdown und Bildern erstellt werden soll (Standard: True)
            
        Returns:
            SessionResponse mit Metadaten, erzeugtem Markdown und optional ZIP-Archiv
        """
        # Hol den Performance-Tracker
        tracker: PerformanceTracker | None = get_performance_tracker()

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
                    video_transcript=video_transcript,
                    attachments_url=attachments_url,
                    source_language=source_language,
                    target_language=target_language,
                    target=target,
                    template=template
                )
                cache_key = self._create_cache_key(input_data)
                
                self.logger.info(f"Starte Verarbeitung von Session: {session}")
                filename = self._sanitize_filename(filename)

                # Verwende die zentrale Methode für Verzeichnis- und Übersetzungslogik
                
                target_dir, _, translated_event = await self._get_translated_entity_directory(
                    event_name=event,
                    track_name=track,
                    target_language=target_language,
                    source_language=source_language,
                    use_translated_names=True
                )
                
                # Übersetze nur den Dateinamen mit der zentralen Methode
                translated_filename = await self._translate_filename(
                    filename=filename,
                    target_language=target_language,
                    source_language=source_language
                )
                
                # Zielverzeichnisstruktur erstellen:
                # sessions/[session]/[track]/[time-session_dir]
                
                # 1. Session-Seite abrufen
                web_text = await self._fetch_session_page(url)
                
                # 2. Video verarbeiten falls vorhanden, oder vorhandenes Transkript verwenden
                video_transcript_text = ""
                if video_transcript:
                    # Verwende das bereits vorhandene Transkript
                    video_transcript_text = video_transcript
                    self.logger.info("Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)")
                elif video_url:
                    # Verarbeite die Video-URL wie bisher
                    video_transcript_text = await self._process_video(
                        video_url=video_url,
                        source_language=source_language,
                        target_language=source_language, # transcript bleibt aus performancegründen immer in originalsprache
                        use_cache=use_cache
                    )
                
                # 3. Anhänge verarbeiten falls vorhanden
                attachment_paths = []
                page_texts: List[str] = []
                asset_dir = ""

                # Verwende für Assets immer den originalen Session-Namen
                
                session_dir_name = f"{Path(filename).stem}"
                if len(session_dir_name) > 50:
                        session_dir_name = session_dir_name[:50]
                
                # Bereinige den Verzeichnisnamen
                session_dir_name = self._sanitize_filename(session_dir_name)

                if attachments_url:
                    attachment_paths, page_texts, asset_dir = await self._process_attachments(
                        attachments_url=attachments_url,
                        session_data=input_data,
                        target_dir= translated_event + "/assets/" + session_dir_name,
                        use_cache=use_cache
                    )
                
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
                    "attachment_paths": attachment_paths,
                    "page_count": len(page_texts),  # Anzahl der Seiten
                    "cache_key": cache_key,
                    "source_language": source_language,
                    "target_language": target_language,
                    "template": template
                }

                template += "_" + target_language
                
                markdown_file, markdown_content, structured_data = await self._generate_markdown(
                    web_text=web_text,
                    video_transcript=video_transcript_text,
                    session_data=input_data,
                    target_dir=target_dir,
                    filename=translated_filename,  # Verwende den übersetzten Dateinamen
                    template=template,
                    context=template_context,
                    page_texts=page_texts
                )
                
                # 5. ZIP-Archiv erstellen (falls gewünscht)
                archive_data = None
                archive_filename = None
                
                if create_archive:
                    try:
                        # Erstelle relativen Pfad zur Markdown-Datei
                        relative_markdown_path = str(markdown_file.relative_to(self.base_dir))
                        
                        archive_data, archive_filename = self._create_session_archive(
                            markdown_content=markdown_content,
                            markdown_file_path=relative_markdown_path,
                            attachment_paths=attachment_paths,
                            asset_dir=asset_dir,
                            session_data=input_data
                        )
                        self.logger.info(f"ZIP-Archiv erstellt: {archive_filename}")
                    except Exception as e:
                        self.logger.warning(f"ZIP-Archiv konnte nicht erstellt werden: {str(e)}")
                        # Fehlschlag ist nicht kritisch, Verarbeitung fortsetzen
                
                # 6. Erstelle Output-Daten
                output_data = SessionOutput(
                    web_text=web_text,
                    video_transcript=video_transcript_text,
                    attachments=attachment_paths,
                    page_texts=page_texts,
                    input_data=input_data,
                    target_dir=str(target_dir),
                    markdown_file=str(markdown_file),
                    markdown_content=markdown_content,
                    structured_data=structured_data,
                    archive_data=archive_data,
                    archive_filename=archive_filename,
                    asset_dir=asset_dir
                )
                
                # 7. Ergebnis im Cache speichern (wenn aktiviert)
                if use_cache and self.is_cache_enabled():
                    result = SessionProcessingResult(
                        web_text=web_text,
                        video_transcript=video_transcript_text,
                        attachment_paths=attachment_paths,
                        page_texts=page_texts,
                        target_dir=str(target_dir),
                        markdown_file=str(markdown_file),
                        markdown_content=markdown_content,
                        process_id=self.process_id,
                        input_data=input_data,
                        structured_data=structured_data
                    )
                    
                    # Im Cache speichern
                    self.save_to_cache(
                        cache_key=cache_key,
                        result=result
                    )
                    self.logger.debug(f"Session-Ergebnis im Cache gespeichert: {cache_key}")
                
                # 8. Response erstellen
                return self.create_response(
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
                    from_cache=False,
                    cache_key=cache_key
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
            
            return self.create_response(
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
                from_cache=False,
                cache_key=""
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
            
            # Verarbeite Sessions sequentiell
            for i, session_data in enumerate(sessions):
                try:
                    # Verarbeite einzelne Session
                    result: SessionResponse = await self.process_session(
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
                        template=session_data.get("template", "Session"),
                        create_archive=session_data.get("create_archive", True)
                    )
                    
                    # Sammle erfolgreiche Ergebnisse
                    if result.data and result.data.output:
                        successful_outputs.append(result.data.output)
                        
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
            
            # Erstelle Response
            return self.create_response(
                processor_name=ProcessorType.SESSION.value,
                result=batch_data,
                request_info={
                    "session_count": len(sessions),
                    "successful": len(successful_outputs),
                    "failed": len(errors)
                },
                response_class=BatchSessionResponse,
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
            
            return self.create_response(
                processor_name=ProcessorType.SESSION.value,
                result=None,
                request_info={
                    "session_count": len(sessions)
                },
                response_class=BatchSessionResponse,
                error=error_info,
                from_cache=False,
                cache_key=""
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
            return self.create_response(
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
            self.logger.error(f"Fehler bei der asynchronen Batch-Session-Verarbeitung: {str(e)}")
            
            return self.create_response(
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
                from_cache=False,
                cache_key=""
            )

    def _create_empty_session_output(self) -> SessionOutput:
        """Erstellt eine leere SessionOutput-Instanz für Fehlerfälle."""
        return SessionOutput(
            web_text="",
            video_transcript="",
            input_data=SessionInput(
                event="",
                session="",
                url="",
                filename="",
                track=""
            ),
            target_dir="",
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
        if "create_archive" not in session:
            session["create_archive"] = True
        
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
        
        # Optionales Video-Transkript hinzufügen (Hash statt voller Text für Cache-Key)
        if session_input.video_transcript:
            # Verwende Hash des Transkripts für Cache-Key (voller Text wäre zu lang)
            import hashlib
            transcript_hash = hashlib.sha256(session_input.video_transcript.encode()).hexdigest()[:16]
            base_key["video_transcript_hash"] = transcript_hash
        
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
        _result: Dict[str, Any] = result.to_dict()
        _input_data: Dict[str, Any] = _result.get("input_data", {})
        _structured_data: Dict[str, Any] = _result.get("structured_data", {})
        # Hauptdaten speichern
        cache_data = {
            "result": _result,
            "processed_at": datetime.now().isoformat(),
            # Da SessionProcessingResult kein metadata-Attribut hat, können wir hier keine weiteren Metadaten hinzufügen
            "target": _input_data.get("target", ""),
            "event": _input_data.get("event", ""),
            "session": _input_data.get("session", ""),
            "track": _input_data.get("track", ""),
            "target_language": _input_data.get("target_language", ""),
            "target": _input_data.get("target", ""),
            "template": _input_data.get("template", ""),
            "topic": _structured_data.get("topic", ""),
            "relevance": _structured_data.get("relevance", "")
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
        
        # Bekannte Felder filtern und unbekannte ignorieren
        filtered_data = {
            "web_text": result_data.get("web_text", ""),
            "video_transcript": result_data.get("video_transcript", ""),
            "attachment_paths": result_data.get("attachment_paths", []),
            "page_texts": result_data.get("page_texts", []),
            "target_dir": result_data.get("target_dir", ""),
            "markdown_content": result_data.get("markdown_content", ""),
            "markdown_file": result_data.get("markdown_file", ""),
            "process_id": result_data.get("process_id"),
            "structured_data": result_data.get("structured_data", {})
        }
        
        # Input-Daten separat behandeln, falls vorhanden
        input_data = result_data.get("input_data", {})
        if input_data:
            filtered_data["input_data"] = input_data
        
        # Sichere Erstellung des SessionProcessingResult, ignoriert unbekannte Felder
        return SessionProcessingResult(**filtered_data)

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

    def get_cache_collection(self) -> Optional[Collection[Dict[str, Any]]]:
        """
        Holt die MongoDB Collection für den Session-Cache.
        
        Returns:
            Optional[Collection[Dict[str, Any]]]: Die Cache-Collection oder None bei Fehlern
        """
        try:
            # Stelle sicher, dass die Verbindung existiert
            if not hasattr(self, 'connection'):
                from src.core.mongodb.connection import get_mongodb_database
                self.connection = get_mongodb_database()
            
            # Stelle sicher, dass der Collection-Name gesetzt ist
            if not self.cache_collection_name:
                self.logger.error("Cache collection name ist nicht gesetzt")
                return None
                
            # Hole die Collection
            try:
                collection = self.connection[self.cache_collection_name]
                return collection
            except Exception as e:
                self.logger.error(f"Fehler beim Zugriff auf Collection '{self.cache_collection_name}': {str(e)}")
                return None
            
        except Exception as e:
            self.logger.error(f"Fehler beim Abrufen der Cache-Collection: {str(e)}")
            return None

    def get_cached_sessions(self) -> List[Dict[str, Any]]:
        """
        Ruft alle Sessions aus dem Cache ab und gibt sie in einer flachen Struktur zurück.
        
        Returns:
            List[Dict[str, Any]]: Liste aller Sessions mit flach strukturierten Daten
        """
        try:
            # Hole die Cache-Collection
            collection: Optional[Collection[Dict[str, Any]]] = self.get_cache_collection()
            if collection is None:
                self.logger.error("Cache-Collection konnte nicht abgerufen werden")
                return []

            # Hole alle Dokumente aus der Collection
            cursor: Cursor[Dict[str, Any]] = collection.find({})
            cached_sessions: List[Dict[str, Any]] = list(cursor)
            flattened_sessions: List[Dict[str, Any]] = []

            for session in cached_sessions:
                try:
                    data = session.get("data", {})
                    # Basis-Session-Daten
                    flattened_session: Dict[str, Any] = {
                        "cache_id": str(session.get("_id", "")),
                        "processed_at": data.get("processed_at", ""),
                        "event": data.get("event", ""),
                        "session": data.get("session", ""),
                        "track": data.get("track", ""),
                        "target_language": data.get("target_language", ""),
                        "target": data.get("target", ""),
                        "template": data.get("template", ""),
                        "topic": data.get("topic", ""),
                        "relevance": data.get("relevance", "")
                    }

                    # Extrahiere Daten aus dem result-Objekt
                    result: Dict[str, Any] = session.get("result", {})
                    if result:
                        # Füge Basis-Informationen hinzu
                        flattened_session.update({
                            "web_text": result.get("web_text", ""),
                            "video_transcript": result.get("video_transcript", ""),
                            "target_dir": result.get("target_dir", ""),
                            "markdown_file": result.get("markdown_file", ""),
                            "attachment_count": len(result.get("attachment_paths", [])),
                            "page_count": len(result.get("page_texts", [])),
                            "process_id": result.get("process_id", "")
                        })

                        # Extrahiere input_data
                        input_data: Dict[str, Any] = result.get("input_data", {})
                        if input_data:
                            flattened_session.update({
                                "url": input_data.get("url", ""),
                                "filename": input_data.get("filename", ""),
                                "day": input_data.get("day", ""),
                                "starttime": input_data.get("starttime", ""),
                                "endtime": input_data.get("endtime", ""),
                                "speakers": ", ".join(input_data.get("speakers", [])),
                                "video_url": input_data.get("video_url", ""),
                                "attachments_url": input_data.get("attachments_url", ""),
                                "source_language": input_data.get("source_language", "")
                            })

                        # Extrahiere structured_data
                        structured_data: Dict[str, Any] = result.get("structured_data", {})
                        if structured_data:
                            # Füge alle Schlüssel aus structured_data hinzu
                            # Prefix mit 'structured_' um Namenskonflikte zu vermeiden
                            for key, value in structured_data.items():
                                str_key: str = str(key)
                                if isinstance(value, (str, int, float, bool)):
                                    flattened_session[f"structured_{str_key}"] = value
                                elif isinstance(value, (list, tuple)):
                                    # Einfache String-Umwandlung ohne Schleife
                                    value_as_str = [str(x) for x in value]  # type: ignore
                                    flattened_session[f"structured_{str_key}"] = ", ".join(value_as_str)
                                elif isinstance(value, dict):
                                    dict_value: Dict[str, Any] = value
                                    for sub_key, sub_value in dict_value.items():
                                        str_sub_key: str = str(sub_key)
                                        str_sub_value: str = str(sub_value)
                                        flattened_session[f"structured_{str_key}_{str_sub_key}"] = str_sub_value

                    flattened_sessions.append(flattened_session)

                except Exception as e:
                    self.logger.warning(f"Fehler beim Verarbeiten einer Session: {str(e)}")
                    continue

            self.logger.info(f"{len(flattened_sessions)} Sessions aus dem Cache abgerufen")
            return flattened_sessions

        except Exception as e:
            self.logger.error(f"Fehler beim Abrufen der gecachten Sessions: {str(e)}")
            return []

    
    async def _get_translated_entity_directory(
        self,
        event_name: str,
        track_name: str,
        target_language: str = "de",
        source_language: str = "de",
        use_translated_names: bool = True
    ) -> Tuple[Path, str, str]:
        """
        Wrapper für die entsprechende Methode in BaseProcessor.
        Verwendet die zentrale Verzeichnis- und Übersetzungslogik für Track und Event-Namen.
        
        Args:
            event_name: Name der Veranstaltung
            track_name: Name des Tracks
            target_language: Zielsprache
            source_language: Quellsprache
            use_translated_names: Ob übersetzte Namen verwendet werden sollen
            
        Returns:
            Tuple aus übersetztem Verzeichnis, übersetztem Track und übersetztem Event
        """
        # Delegiere an die Basisklasse
        return await super()._get_translated_entity_directory(
            event_name=event_name,
            track_name=track_name,
            target_language=target_language,
            source_language=source_language,
            use_translated_names=use_translated_names
        )

    async def _translate_filename(self, filename: str, target_language: str, source_language: str) -> str:
        """
        Wrapper für die entsprechende Methode in BaseProcessor.
        Übersetzt einen Dateinamen in die Zielsprache.
        
        Args:
            filename: Der zu übersetzende Dateiname
            target_language: Zielsprache
            source_language: Quellsprache
            
        Returns:
            Übersetzter Dateiname
        """
        # Delegiere an die Basisklasse
        return await super()._translate_filename(
            filename=filename,
            target_language=target_language,
            source_language=source_language
        )
