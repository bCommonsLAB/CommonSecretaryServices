"""
@fileoverview Base Processor - Common base class for all processors

@description
Base processor module that defines the common interface and functionality for all processors.
This class provides the foundation for all processors in the system and defines common
functionality such as:
- Process ID management and hierarchical tracking
- Logger initialization
- Resource tracking
- Configuration management
- Validation methods
- Template processing
- MongoDB database access

All specific processors inherit from BaseProcessor and extend its functionality.

Features:
- Generic typing with TypeVar for processor-specific types
- ProcessInfo management with LLM tracking
- Hierarchical tracking of sub-processors
- Validation methods for text, language, format
- Template loading and processing
- Configuration management per processor

@module processors.base_processor

@exports
- BaseProcessor: Generic class - Base class for all processors

@usedIn
- src.processors.cacheable_processor: Inherits from BaseProcessor
- src.processors.*: All specific processors inherit from BaseProcessor or CacheableProcessor
- src.core.models.base: Uses BaseProcessor for ProcessInfo access

@dependencies
- External: pymongo - MongoDB database access
- External: yaml - Template processing
- Internal: src.core.exceptions - ValidationError
- Internal: src.core.models.base - ErrorInfo, ProcessInfo, RequestInfo, BaseResponse
- Internal: src.core.models.enums - ProcessingStatus
- Internal: src.core.config - Config
- Internal: src.utils.logger - ProcessingLogger
- Internal: src.core.resource_tracking - ResourceCalculator
"""
import uuid
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, ContextManager, Dict, Optional, BinaryIO, Tuple, TypeVar, Type, Generic, List, Union
import os
import time
from pymongo.collection import Collection
from pymongo.database import Database

import yaml
import re

from src.core.exceptions import ValidationError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo, LLMInfo, BaseResponse
from src.core.models.llm import LLMRequest
from src.core.models.enums import ProcessingStatus
from src.core.config import Config
from src.utils.logger import ProcessingLogger, get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.core.resource_tracking import ResourceCalculator

T = TypeVar('T')
R = TypeVar('R', bound=BaseResponse)


class BaseProcessor(Generic[T]):
    """
    Basis-Klasse für alle Prozessoren.
    Definiert gemeinsame Funktionalität und Schnittstellen.
    
    Attributes:
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        temp_dir (Path): Temporäres Verzeichnis für Verarbeitungsdateien
        logger (ProcessingLogger): Logger-Instanz für den Processor
        resource_calculator (ResourceCalculator): Calculator für Ressourcenverbrauch
        process_info (ProcessInfo): Informationen über den Verarbeitungsprozess und LLM-Aufrufen
    """
    
    # Konstanten für Validierung
    SUPPORTED_LANGUAGES = {'de', 'en', 'fr', 'es', 'it'}  # Beispiel, sollte aus Config kommen
    SUPPORTED_FORMATS = {'text', 'html', 'markdown'}
    
    _current_process_info: Optional[ProcessInfo] = None  # Klassenvariable für die aktuelle ProcessInfo

    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None) -> None:
        """
        Initialisiert den BaseProcessor.
        
        Args:
            resource_calculator (ResourceCalculator): Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID. 
                                      Wenn None, wird eine neue UUID generiert.
                                      Im Normalfall sollte diese ID vom API-Layer kommen.
            parent_process_info (ProcessInfo, optional): ProcessInfo des aufrufenden Prozessors
                                                       für hierarchisches LLM-Tracking
        """
        self.process_id = process_id or str(uuid.uuid4())
        self.resource_calculator: ResourceCalculator = resource_calculator
        self.logger: ProcessingLogger = self.init_logger()
        self.base_dir: Path = Path("output")  # Basis-Verzeichnis für alle Ausgaben
        
        if parent_process_info:
            self.process_info = parent_process_info
            if self.__class__.__name__ not in self.process_info.sub_processors:
                self.process_info.sub_processors.append(self.__class__.__name__)
        else:
            self.process_info: ProcessInfo = ProcessInfo(
                id=self.process_id,
                main_processor=self.__class__.__name__,
                started=datetime.now().isoformat(),
                sub_processors=[],
                llm_info=LLMInfo()  # Initialisiere llm_info
            )
        
        # Setze die aktuelle ProcessInfo für die Response-Erstellung
        BaseProcessor._current_process_info = self.process_info

        # Verwende Prozessor-spezifische Konfiguration für Cache
        processor_name = self.__class__.__name__.lower().replace('processor', '')
        processor_config = self.load_processor_config(processor_name)
        
        # Initialisiere den Cache-Pfad und den Temp-Pfad
        self.cache_dir = self.get_cache_dir(processor_name, processor_config)
        self.temp_dir = self.get_cache_dir(processor_name, processor_config, subdirectory="temp")

        self._db: Optional[Database[Dict[str, Any]]] = None

    @property
    def db(self) -> Database[Dict[str, Any]]:
        """MongoDB Datenbank-Instanz."""
        if self._db is None:
            raise RuntimeError("Database not initialized")
        return self._db

    @classmethod
    def get_current_process_info(cls) -> Optional[ProcessInfo]:
        """Gibt die aktuelle ProcessInfo zurück."""
        return cls._current_process_info

    def __del__(self):
        """Cleanup beim Löschen des Prozessors."""
        BaseProcessor._current_process_info = None  # Reset der aktuellen ProcessInfo

    def validate_text(self, text: Optional[str], field_name: str = "text") -> str:
        """
        Validiert einen Text-Input.
        
        Args:
            text: Der zu validierende Text
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Text
            
        Raises:
            ValidationError: Wenn der Text ungültig ist
        """
        if not text:
            raise ValidationError(f"{field_name} darf nicht leer sein")
        
        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValidationError(f"{field_name} darf nicht nur aus Whitespace bestehen")
            
        return cleaned_text

    def validate_language_code(self, language_code: Optional[str], field_name: str = "language") -> str:
        """
        Validiert einen Sprach-Code.
        
        Args:
            language_code: Der zu validierende Sprach-Code
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Sprach-Code
            
        Raises:
            ValidationError: Wenn der Sprach-Code ungültig ist
        """
        if not language_code:
            raise ValidationError(f"{field_name} muss angegeben werden")
            
        language_code = language_code.lower()
        if language_code not in self.SUPPORTED_LANGUAGES:
            raise ValidationError(f"Nicht unterstützter {field_name}: {language_code}")
            
        return language_code

    def validate_format(self, format_str: Optional[str], default: str = "text") -> str:
        """
        Validiert ein Format.
        
        Args:
            format_str: Das zu validierende Format
            default: Standard-Format wenn keins angegeben
            
        Returns:
            str: Das validierte Format
            
        Raises:
            ValidationError: Wenn das Format ungültig ist
        """
        if not format_str:
            return default
            
        if format_str not in self.SUPPORTED_FORMATS:
            if self.logger:
                self.logger.warning(f"Ungültiges Format '{format_str}', verwende '{default}'")
            return default
            
        return format_str

    def validate_context(self, context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Validiert einen Kontext.
        
        Args:
            context: Der zu validierende Kontext
            
        Returns:
            Optional[Dict[str, Any]]: Der validierte Kontext oder None
        """
        if context is None:
            return None
            
        try:
            # Versuche auf dict-spezifische Methoden zuzugreifen
            context.keys()
            context.values()
            return context
        except AttributeError:
            if self.logger:
                self.logger.warning("Context ist kein Dictionary, wird ignoriert",
                    context_type=type(context).__name__,
                    context_value=str(context)[:200] if context else None)
            return None

    def init_temp_dir(self, processor_name: str, config: Optional[Dict[str, Any]] = None) -> Path:
        """
        DEPRECATED: Diese Methode wird in zukünftigen Versionen entfernt. 
        Bitte verwenden Sie get_cache_dir mit subdirectory="temp".
        
        Behält die Abwärtskompatibilität für bestehende Prozessoren.
        
        Args:
            processor_name (str): Name des Processors (ohne "processor" am Ende)
            config (Dict[str, Any], optional): Processor-Konfiguration, falls vorhanden
            
        Returns:
            Path: Pfad zum temporären Verzeichnis
        """
        self.logger.warning(
            "Die Methode init_temp_dir ist veraltet und wird in zukünftigen Versionen entfernt. "
            "Bitte verwenden Sie get_cache_dir mit subdirectory='temp'."
        )
        
        # Rufe get_cache_dir mit dem Unterverzeichnis 'temp' auf
        return self.get_cache_dir(processor_name, config, subdirectory="temp")

    def get_upload_temp_file(self, suffix: str = "", prefix: str = "upload_", delete: bool = False) -> Tuple[BinaryIO, str]:
        """
        Erstellt eine benannte temporäre Datei im konfigurierten temporären Verzeichnis.
        Diese Methode sollte anstelle von tempfile.NamedTemporaryFile in Route-Handlern verwendet werden.
        
        Args:
            suffix (str): Optionale Dateierweiterung (z.B. ".pdf")
            prefix (str): Optionales Präfix für den Dateinamen
            delete (bool): Ob die Datei automatisch gelöscht werden soll (nicht empfohlen)
            
        Returns:
            Tuple[BinaryIO, str]: Ein Tupel aus (Datei-Objekt, Dateipfad)
            
        Beispiel:
            temp_file, temp_path = processor.get_upload_temp_file(suffix=".pdf")
            with open(temp_path, 'wb') as f:
                f.write(content)
            # oder
            temp_file.write(content)
            temp_file.flush()
        """
        # Erstelle einen eindeutigen Dateinamen
        temp_filename = f"{prefix}{uuid.uuid4().hex}{suffix}"
        
        # Verwende das temp-Unterverzeichnis im Cache
        if not hasattr(self, 'temp_dir'):
            # Fallback für Abwärtskompatibilität, falls temp_dir noch nicht initialisiert ist
            processor_name = self.__class__.__name__.lower().replace('processor', '')
            self.temp_dir = self.get_cache_dir(processor_name, subdirectory="temp")
            
        temp_path = self.temp_dir / "uploads" / temp_filename
        
        # Stelle sicher, dass das Upload-Verzeichnis existiert
        (self.temp_dir / "uploads").mkdir(parents=True, exist_ok=True)
        
        # Erstelle die Datei
        temp_file = open(str(temp_path), 'wb+')
        
        # Wenn delete=True, registriere die Datei zum automatischen Löschen
        if delete:
            temp_file.close()
            temp_file = open(str(temp_path), 'wb+')
            
            # Lösche die Datei beim Schließen
            original_close = temp_file.close
            def new_close():
                original_close()
                try:
                    os.unlink(str(temp_path))
                except Exception as e:
                    # Stille Ausnahme, aber wir könnten hier loggen
                    if self.logger:
                        self.logger.debug(f"Fehler beim Löschen der temporären Datei: {e}")
                    pass
            temp_file.close = new_close
            
        return temp_file, str(temp_path)

    def get_cache_dir(self, processor_name: str, config: Optional[Dict[str, Any]] = None, 
                      subdirectory: Optional[str] = None) -> Path:
        """
        Gibt das Cache-Verzeichnis für den Processor zurück. 
        Optional kann ein Unterverzeichnis angegeben werden, z.B. "temp" für temporäre Dateien
        oder "processed" für verarbeitete Dateien.
        
        Args:
            processor_name (str): Name des Processors für den Unterordner
            config (Dict[str, Any], optional): Processor-Konfiguration, falls vorhanden
            subdirectory (str, optional): Optionales Unterverzeichnis im Cache
            
        Returns:
            Path: Pfad zum Cache-Verzeichnis
        """
        # Lade die Basis-Konfiguration
        app_config = Config()
        cache_base = Path(app_config.get('cache', {}).get('base_dir', './cache'))
        
        if config and 'cache_dir' in config:
            # Verwende konfigurierten Pfad
            cache_path = config.get('cache_dir')
            base_cache_dir = Path(str(cache_path))
        else:
            # Erstelle Standard-Pfad im Cache-Verzeichnis
            base_cache_dir = cache_base / processor_name.lower()
        
        # Wenn ein Unterverzeichnis angegeben ist, füge es zum Pfad hinzu
        if subdirectory:
            cache_dir = base_cache_dir / subdirectory
        else:
            cache_dir = base_cache_dir
            
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def init_logger(self, processor_name: Optional[str] = None) -> ProcessingLogger:
        """
        Initialisiert den Logger für den Processor.
        
        Args:
            processor_name (str, optional): Name des Processors. 
                                          Wenn None, wird der Klassenname verwendet.
        """
        if processor_name is None:
            processor_name = self.__class__.__name__
        self.logger = get_logger(process_id=self.process_id, processor_name=processor_name)
        return self.logger

    def measure_operation(self, operation_name: str) -> ContextManager[object]:
        """
        Context Manager zum Messen der Performance einer Operation.
        
        Args:
            operation_name (str): Name der Operation die gemessen werden soll
            
        Returns:
            ContextManager[object]: Context Manager für die Performance-Messung
        """
        tracker = get_performance_tracker()
        if tracker:
            return tracker.measure_operation(operation_name, self.__class__.__name__)
        return nullcontext()

    def load_processor_config(self, processor_name: str) -> Dict[str, Any]:
        """
        Lädt die Konfiguration für einen spezifischen Processor aus der config.yaml.
        
        Args:
            processor_name (str): Name des Processors (z.B. 'transformer', 'metadata')
            
        Returns:
            Dict[str, Any]: Processor-spezifische Konfiguration
            
        Raises:
            KeyError: Wenn keine Konfiguration für den Processor gefunden wurde
        """
        try:
            # Lade die Konfigurationsdatei
            config_path = Path("config/config.yaml")
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            
            # Hole die processor-spezifische Konfiguration
            processor_config = config.get("processors", {}).get(processor_name, {})
            
            if not processor_config and self.logger:
                self.logger.warning(
                    f"Keine Konfiguration für Processor '{processor_name}' gefunden",
                    processor=processor_name
                )
            
            return processor_config
            
        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Fehler beim Laden der Processor-Konfiguration",
                    error=e,
                    processor=processor_name
                )
            return {}

    def create_response(
        self,
        processor_name: str,
        result: Any,
        request_info: Dict[str, Any],
        response_class: Type[R],
        from_cache: bool,
        cache_key: str,
        error: Optional[ErrorInfo] = None
    ) -> R:
        """
        Erstellt eine standardisierte Response mit hierarchischem LLM-Tracking.
        
        Args:
            processor_name: Name des Processors
            result: Das Ergebnis der Verarbeitung
            request_info: Request-Parameter
            response_class: Die zu erstellende Response-Klasse
            from_cache: Flag, das anzeigt, ob das Ergebnis aus dem Cache stammt
            cache_key: Der Cache-Schlüssel für das Ergebnis
            error: Optional, Fehlerinformationen
            
        Returns:
            R: Die standardisierte Response vom angegebenen Typ
        """
        
        self.process_info.is_from_cache = from_cache
        self.process_info.cache_key = cache_key
            
        # Erstelle die Response
        response = response_class(
            request=RequestInfo(
                processor=processor_name,
                timestamp=datetime.now().isoformat(),
                parameters=request_info
            ),
            process=self.process_info,
            status=ProcessingStatus.ERROR if error else ProcessingStatus.SUCCESS,
            error=error,
            data=result.data if hasattr(result, 'data') and result.data is not None else result
        )
            
        return response
    
    def add_llm_requests(self, requests: Union[List[LLMRequest], LLMInfo]) -> None:
        """
        Fügt LLM-Requests zur ProcessInfo hinzu.
        
        Args:
            requests: Liste von LLMRequests oder LLMInfo Objekt
        """
            
        # Konvertiere LLMInfo zu Liste von Requests wenn nötig
        if isinstance(requests, LLMInfo):
            if self.process_info.llm_info is None:
                self.process_info.llm_info = requests
            else:
                self.process_info.llm_info = self.process_info.llm_info.merge(requests)
        else:
            if self.process_info.llm_info is None:
                self.process_info.llm_info = LLMInfo(requests=[requests] if isinstance(requests, LLMRequest) else requests)
            else:
                self.process_info.llm_info = self.process_info.llm_info.add_request(requests)
        
        # Log für Debugging
        if hasattr(self, 'logger'):
            num_requests = len(requests.requests) if isinstance(requests, LLMInfo) else len(requests)
            self.logger.debug(f"{num_requests} LLM-Requests hinzugefügt")

    def create_ttl_index(self, collection_name: str, field: str, expire_after_seconds: int) -> None:
        """
        Erstellt einen TTL-Index mit Retry-Logik.
        
        Args:
            collection_name: Name der Collection
            field: Feld für den TTL-Index
            expire_after_seconds: Zeit bis zum Ablauf in Sekunden
        """
        max_retries = 3
        retry_delay = 1  # Sekunden
        
        for attempt in range(max_retries):
            try:
                collection: Collection[Dict[str, Any]] = self.db[collection_name]
                collection.create_index(
                    [(field, 1)],
                    expireAfterSeconds=expire_after_seconds,
                    background=True
                )
                self.logger.info(f"TTL-Index erfolgreich erstellt für {collection_name}.{field}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"Versuch {attempt + 1}/{max_retries} fehlgeschlagen: {str(e)}")
                    time.sleep(retry_delay)
                    continue
                self.logger.error(f"Fehler beim Erstellen des TTL-Index für {collection_name}: {str(e)}")
                raise

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für die Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Basis-Indizes
            collection.create_index("created_at")
            collection.create_index("updated_at")
            
            # TTL-Index für Cache-Einträge
            self.create_ttl_index(
                collection_name=collection.name,
                field="created_at",
                expire_after_seconds=3600  # 1 Stunde
            )
            
            # Weitere spezifische Indizes je nach Collection
            if collection.name == "transformer_cache":
                collection.create_index("source_language")
                collection.create_index("target_language")
            elif collection.name == "video_cache":
                collection.create_index("status")
                collection.create_index("duration")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen der spezialisierten Indizes: {str(e)}")
            raise

    def _sanitize_filename(self, name: str) -> str:
        """
        Bereinigt einen Datei- oder Verzeichnisnamen.
        Entfernt ungültige Zeichen und ersetzt Leerzeichen durch Unterstriche.
        
        Args:
            name: Der zu bereinigende Name
            
        Returns:
            str: Der bereinigte Name
        """
        # Ersetze ungültige Zeichen durch Unterstriche
        invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
        sanitized = re.sub(invalid_chars, '_', name)
        
        # Entferne doppelte Unterstriche
        sanitized = re.sub(r'_+', '_', sanitized)
        sanitized = sanitized.replace("-", " ")

        # Entferne führende und abschließende Unterstriche
        sanitized = sanitized.strip('_')
        
        # Stelle sicher, dass der Name nicht leer ist
        if not sanitized:
            sanitized = 'unnamed'
            
        # Kürze den Namen, falls er zu lang ist
        if len(sanitized) > 50:
            sanitized = sanitized[:50].strip() + ".md"
            
        return sanitized

    async def _translate_entity_name(
        self, 
        entity_type: str, 
        entity_id: str, 
        entity_text: str, 
        target_language: str, 
        source_language: str
    ) -> str:
        """
        Übersetzt einen Entitätsnamen (Event, Track, Session, Dateiname) und
        stellt die Konsistenz der Übersetzung über mehrere Aufrufe sicher.
        
        Args:
            entity_type: Typ der Entität ('event', 'track', 'session', 'filename')
            entity_id: ID oder eindeutiger Bezeichner der Entität
            entity_text: Text, der übersetzt werden soll
            target_language: Zielsprache 
            source_language: Quellsprache
            
        Returns:
            str: Der übersetzte und bereinigte Entitätsname
        """
        
            
        # Translator-Service laden
        from src.core.services.translator_service import get_translator_service
        translator = get_translator_service()
        
        # Entität übersetzen
        translated_text = await translator.translate_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            text=entity_text,
            target_language=target_language,
            source_language=source_language
        )
        
        # Nach der Übersetzung auf Sonderzeichen prüfen und bereinigen
        sanitized_translated_text = self._sanitize_filename(translated_text)
        
        # Sicherstellen, dass der Name nicht zu lang wird
        if len(sanitized_translated_text) > 50:
            sanitized_translated_text = sanitized_translated_text[:50]
            
        return sanitized_translated_text
        
    async def _translate_filename(
        self,
        filename: str,
        target_language: str,
        source_language: str
    ) -> str:
        """
        Übersetzt einen Dateinamen, wobei nur der Stammteil übersetzt wird und
        die Dateierweiterung erhalten bleibt.
        
        Args:
            filename: Der zu übersetzende Dateiname
            target_language: Zielsprache
            source_language: Quellsprache
            
        Returns:
            str: Der übersetzte und bereinigte Dateiname
        """
                    
        # Dateiname in Stamm und Erweiterung aufteilen
        path = Path(filename)
        stem = path.stem
        suffix = path.suffix
        
        # Stammteil übersetzen
        translated_stem = await self._translate_entity_name(
            entity_type="filename",
            entity_id=stem,
            entity_text=stem,
            target_language=target_language,
            source_language=source_language
        )
        
        # Übersetzten Dateinamen zusammensetzen
        return f"{translated_stem}{suffix}"
    
    async def _get_translated_entity_directory(
        self,
        event_name: str,
        track_name: str,
        target_language: str = "de",
        source_language: str = "de",
        use_translated_names: bool = True
    ) -> Tuple[Path, str, str]:
        """
        Ermittelt das Verzeichnis für eine Entität mit Übersetzung der Namen.
        
        Args:
            event_name: Name des Events
            track_name: Name des Tracks
            target_language: Zielsprache (default: "de")
            source_language: Quellsprache (default: "de")
            use_translated_names: Ob übersetzte Namen verwendet werden sollen
            
        Returns:
            Tuple[Path, str, str]: (Verzeichnispfad, übersetzter Track-Name, übersetzter Event-Name)
        """
        # Sanitize original names for consistent IDs
        sanitized_event_id = self._sanitize_filename(event_name)
        
        translated_event = event_name
        translated_track = track_name
        
        if use_translated_names:
            # Übersetze die Namen
            translated_event = await self._translate_entity_name(
                entity_type="event",
                entity_id=sanitized_event_id,
                entity_text=event_name,
                target_language=target_language,
                source_language=source_language
            )
            
            translated_track = await self._translate_entity_name(
                entity_type="track",
                entity_id=track_name,
                entity_text=track_name,
                target_language=target_language,
                source_language=source_language
            )
        
        # Sanitize translated names for directory creation
        sanitized_event = self._sanitize_filename(translated_event)
        sanitized_track = self._sanitize_filename(translated_track)
        
        # Erstelle den Verzeichnispfad
        base_path: Path = self.base_dir / sanitized_event / target_language / sanitized_track
        
        # Stelle sicher, dass das Verzeichnis existiert
        base_path.mkdir(parents=True, exist_ok=True)
        
        return base_path, translated_track, translated_event
    