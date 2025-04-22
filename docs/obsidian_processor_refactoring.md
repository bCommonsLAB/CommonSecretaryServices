# Refaktorierung des Obsidian-Prozessors

## Ausgangslage

Der aktuelle Obsidian-Prozessor hat folgende Limitierungen:

1. **Verzeichnisbasierte Analyse**: Der Prozessor analysiert die Verzeichnisstruktur direkt, statt strukturierte Daten aus der MongoDB zu nutzen
2. **Fehlende Standardisierung**: Verwendet nicht die zentrale BaseProcessor-Struktur für Cache-Zugriff, Logging und Responses
3. **Fehlerbehandlung**: Unzureichende Fehlerbehandlung bei nicht vorhandenen Dateien oder Strukturen

## Ziele der Refaktorierung

1. **Datenbankbasierte Analyse**: Nutzung der MongoDB-Daten für die Struktur- und Metadaten-Informationen
2. **Standardisierte Prozessorstruktur**: Implementierung nach dem BaseProcessor-Pattern
3. **Robuste Fehlerbehandlung**: Klare Fehlermeldungen und -behandlung
4. **Verbesserte Caching-Mechanismen**: Nutzung der standardisierten Cache-Funktionalität

## Implementierungsplan

### 1. Neue Klassenstruktur

```python
class ObsidianProcessingResult:
    """
    Ergebnisstruktur für die Obsidian-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        source_dir: str,
        target_dir: str,
        event_name: str,
        languages: List[str],
        export_mode: str,
        progress: ExportProgress,
        mappings: List[ExportMapping],
        event_info: Optional[EventInfo] = None,
        process_id: Optional[str] = None
    ):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.event_name = event_name
        self.languages = languages
        self.export_mode = export_mode
        self.progress = progress
        self.mappings = mappings
        self.event_info = event_info
        self.process_id = process_id
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "event_name": self.event_name,
            "languages": self.languages,
            "export_mode": self.export_mode,
            "progress": self.progress.to_dict(),
            "mappings": [m.to_dict() for m in self.mappings],
            "event_info": self.event_info.to_dict() if self.event_info else None,
            "process_id": self.process_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ObsidianProcessingResult':
        """Erstellt ein ObsidianProcessingResult aus einem Dictionary."""
        # Implementation...
        
    def to_response(self, response_class) -> Any:
        """Konvertiert das Ergebnis in eine Response-Klasse."""
        # Implementation...


class ObsidianProcessor(CacheableProcessor[ObsidianProcessingResult]):
    """
    Prozessor für den Export von Event-Daten nach Obsidian.
    
    Diese Klasse nutzt MongoDB-Daten für die Struktur- und Metadaten-Informationen
    und exportiert die Daten in ein für Obsidian optimiertes Format.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "obsidian_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, config: Optional[ObsidianExportConfig] = None, 
                 process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None) -> None:
        """Initialisiert den ObsidianProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Konfiguration
        self.config = config
        self.progress = ExportProgress()
        self.event_info: Optional[EventInfo] = None
        self.mappings: List[ExportMapping] = []
        
        # MongoDB-Verbindung initialisieren
        self._init_mongodb()
        
        # Cache initialisieren
        self.cache = ProcessorCache[ObsidianProcessingResult](str(self.cache_collection_name))
        
    # Weitere Methoden...
```

### 2. MongoDB-Integration

Der refaktorierte Prozessor soll die MongoDB nutzen, um:

1. **Event-Strukturen zu laden**: Welche Events und Tracks existieren
2. **Session-Daten abzurufen**: Metadaten und Pfade zu Markdowndateien
3. **Verfügbare Sprachen zu identifizieren**: Welche Übersetzungen existieren

```python
async def _load_event_structure_from_db(self, event_name: str) -> EventInfo:
    """
    Lädt die Event-Struktur aus der MongoDB.
    
    Args:
        event_name: Name des Events
        
    Returns:
        EventInfo: Die Event-Struktur
    """
    # Finde alle Sessions für das Event
    sessions = list(self.session_jobs.find(
        {"parameters.event": event_name, "status": "completed"}
    ).sort("completed_at", -1))
    
    if not sessions:
        raise ValueError(f"Keine Sessions für Event '{event_name}' gefunden")
    
    # Event-Struktur erstellen
    event_info = EventInfo(
        id=event_name.lower().replace(" ", "-"),
        name=event_name,
        path="",  # Wird später aktualisiert
        tracks=[],
        summary_files={}
    )
    
    # Tracks identifizieren
    track_names = set(doc.get("parameters", {}).get("track", "") for doc in sessions if doc.get("parameters", {}).get("track"))
    
    # Track-Strukturen erstellen
    for track_name in track_names:
        track_sessions = [s for s in sessions if s.get("parameters", {}).get("track") == track_name]
        
        # Track-Info erstellen
        track_info = self._create_track_info_from_db(track_name, track_sessions)
        event_info.tracks.append(track_info)
    
    return event_info

def _create_track_info_from_db(self, track_name: str, track_sessions: List[Dict[str, Any]]) -> TrackInfo:
    """Erstellt TrackInfo aus Datenbank-Dokumenten."""
    # Implementation...
    
def _create_session_info_from_db(self, session_doc: Dict[str, Any]) -> SessionInfo:
    """Erstellt SessionInfo aus einem Datenbank-Dokument."""
    # Implementation...
```

### 3. Verbessertes Cache-Management

```python
def _generate_cache_key(
    self,
    event_name: str,
    export_mode: str,
    languages: List[str]
) -> str:
    """Generiert einen Cache-Schlüssel für den Export."""
    base_key = ProcessorCache.generate_simple_key(event_name)
    param_str = f"{export_mode}_{'-'.join(sorted(languages))}"
    return hashlib.sha256(f"{base_key}_{param_str}".encode()).hexdigest()

def _check_cache(
    self,
    cache_key: str
) -> Optional[Tuple[ObsidianProcessingResult, Dict[str, Any]]]:
    """Prüft, ob ein Cache-Eintrag für den Export existiert."""
    return self.cache.load_cache_with_key(
        cache_key=cache_key,
        result_class=ObsidianProcessingResult
    )

def _save_to_cache(
    self,
    cache_key: str,
    result: ObsidianProcessingResult
) -> None:
    """Speichert ein Exportergebnis im Cache."""
    metadata = {
        'event_name': result.event_name,
        'export_mode': result.export_mode,
        'languages': result.languages,
        'process_id': self.process_id
    }
    
    self.cache.save_cache_with_key(
        cache_key=cache_key,
        result=result,
        metadata=metadata
    )
```

### 4. Hauptexport-Methode

```python
async def export(
    self,
    config: Optional[ObsidianExportConfig] = None,
    use_cache: bool = True
) -> ObsidianResponse:
    """
    Führt den Export gemäß der Konfiguration durch.
    
    Args:
        config: Optionale Konfiguration (überschreibt die Konfiguration aus dem Constructor)
        use_cache: Ob der Cache verwendet werden soll
        
    Returns:
        ObsidianResponse: Das Ergebnis des Exports
    """
    start_time = time.time()
    
    # Konfiguration sicherstellen
    if config:
        self.config = config
    
    if not self.config:
        return self.create_response(
            processor_name="obsidian",
            result=None,
            request_info={},
            response_class=ObsidianResponse,
            error=ErrorInfo(
                code="CONFIG_ERROR",
                message="Keine Konfiguration vorhanden"
            )
        )
    
    try:
        # Cache-Key generieren
        cache_key = self._generate_cache_key(
            event_name=self.config.event_name,
            export_mode=self.config.export_mode,
            languages=self.config.languages
        )
        
        # Cache prüfen
        if use_cache:
            cache_result = self._check_cache(cache_key)
            if cache_result:
                result, _ = cache_result
                return self.create_response(
                    processor_name="obsidian",
                    result=result.progress,
                    request_info=self.config.to_dict(),
                    response_class=ObsidianResponse,
                    from_cache=True,
                    cache_key=cache_key
                )
        
        # Export durchführen
        self.progress.start_time = datetime.now()
        self.progress.status = "running"
        
        # Event-Struktur aus der Datenbank laden
        self.event_info = await self._load_event_structure_from_db(self.config.event_name)
        
        # Je nach Export-Modus ausführen
        if self.config.export_mode == "copy":
            await self._execute_copy_mode()
        elif self.config.export_mode == "regenerate":
            await self._execute_regenerate_mode()
        elif self.config.export_mode == "hybrid":
            await self._execute_hybrid_mode()
        else:
            raise ValueError(f"Ungültiger Export-Modus: {self.config.export_mode}")
        
        self.progress.status = "completed"
        self.progress.end_time = datetime.now()
        
        # Ergebnis im Cache speichern
        result = ObsidianProcessingResult(
            source_dir=self.config.source_dir,
            target_dir=self.config.target_dir,
            event_name=self.config.event_name,
            languages=self.config.languages,
            export_mode=self.config.export_mode,
            progress=self.progress,
            mappings=self.mappings,
            event_info=self.event_info,
            process_id=self.process_id
        )
        
        self._save_to_cache(cache_key, result)
        
        # Response erstellen
        return self.create_response(
            processor_name="obsidian",
            result=self.progress,
            request_info=self.config.to_dict(),
            response_class=ObsidianResponse,
            from_cache=False,
            cache_key=cache_key
        )
        
    except Exception as e:
        self.progress.status = "failed"
        self.progress.error = str(e)
        self.progress.end_time = datetime.now()
        
        return self.create_response(
            processor_name="obsidian",
            result=self.progress,
            request_info=self.config.to_dict() if self.config else {},
            response_class=ObsidianResponse,
            error=ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
        )
```

## Migration und Testplan

### 1. Schrittweise Migration

1. **BaseProcessor-Struktur implementieren**: Klassen umstellen, ohne Funktionalität zu ändern
2. **MongoDB-Integration hinzufügen**: Funktionalität zur Abfrage der Datenbank implementieren
3. **Cache-Integration verbessern**: Standardisierten Cache-Mechanismus nutzen
4. **API-Endpunkte anpassen**: Parameter und Rückgabewerte anpassen

### 2. Testplan

1. **Unit-Tests für neue Funktionen**: 
   - Tests für MongoDB-Integration
   - Tests für Cache-Funktionalität
   - Tests für Export-Funktionen

2. **Integrationstests**:
   - Test des Gesamtablaufs mit MongoDB-Daten
   - Verifikation der erzeugten Obsidian-Struktur
   - Prüfung der Fehlerbehandlung

3. **API-Tests**:
   - Test der API-Endpunkte mit verschiedenen Parametern
   - Prüfung der Response-Struktur

## Erweiterungen für die Zukunft

1. **Status-Tracking**: Detailliertes Tracking des Export-Status in Echtzeit
2. **Inkrementeller Export**: Nur Änderungen exportieren
3. **Verbesserte Fehlerbehandlung**: Detaillierte Fehlerberichte mit Vorschlägen zur Lösung
4. **Erweiterte Metadaten**: Zusätzliche Metadaten für Obsidian-Dateien 