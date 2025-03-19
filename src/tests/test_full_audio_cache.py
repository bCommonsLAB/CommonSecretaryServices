"""
Vollständiger Test für den AudioProcessor mit MongoDB-Caching.
"""
import sys
import os
import logging
import asyncio
import uuid
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List, TypedDict, Protocol
from dataclasses import dataclass
from datetime import datetime

import pytest

from src.core.config import Config
from src.core.resource_tracking import ResourceCalculator
from src.core.mongodb.connection import get_mongodb_database
from src.processors.audio_processor import AudioProcessor, WhisperTranscriberProtocol
from src.utils.performance_tracker import get_performance_tracker
from src.processors.base_processor import BaseProcessor
from src.core.models.audio import (
    AudioSegmentInfo, 
    Chapter, 
    TranscriptionResult, 
    WhisperSegment,
    TranscriptionSegment
)
from src.core.models.llm import LLMRequest, LLModel
from src.utils.logger import ProcessingLogger

# Logger einrichten
logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def create_test_audio_file() -> Path:
    """
    Erstellt eine temporäre Testdatei für Audio-Tests.
    
    Returns:
        Path: Pfad zur Testdatei
    """
    # Erstelle temporäre Datei
    temp_dir = tempfile.gettempdir()
    temp_file = Path(temp_dir) / f"test_audio_{uuid.uuid4()}.mp3"
    
    # Prüfe, ob eine Beispiel-Audiodatei im Projekt vorhanden ist
    sample_paths = [
        Path("tests/samples/sample_audio.mp3"),
        Path("src/tests/samples/sample_audio.mp3"),
        Path("tests/data/audio/sample.mp3"),
        Path("src/tests/data/audio/sample.mp3")
    ]
    
    sample_file = None
    for path in sample_paths:
        if path.exists():
            sample_file = path
            break
    
    if sample_file:
        # Kopiere die Beispieldatei
        with open(sample_file, "rb") as src_file:
            with open(temp_file, "wb") as dst_file:
                dst_file.write(src_file.read())
        logger.info(f"Testdatei erstellt: {temp_file}")
        return temp_file
    else:
        # Erstelle eine leere MP3-Datei
        with open(temp_file, "wb") as f:
            # Minimale MP3-Header-Daten
            f.write(bytes.fromhex("FFFB9064000169000000000000000000"))
        logger.info(f"Leere Testdatei erstellt: {temp_file}")
        return temp_file

async def test_audio_processor_with_caching():
    """
    Testet den AudioProcessor mit MongoDB-Caching.
    """
    logger.info("Teste AudioProcessor mit MongoDB-Caching...")
    
    # Testdatei erstellen
    test_file = create_test_audio_file()
    logger.info(f"Testdatei: {test_file}")
    
    # ResourceCalculator für Performance-Tracking initialisieren
    resource_calculator = ResourceCalculator()
    
    # AudioProcessor mit zufälliger Process-ID erstellen
    process_id = str(uuid.uuid4())
    processor = AudioProcessor(resource_calculator, process_id)
    
    # Prüfe, ob der Cache aktiviert ist
    is_cache_enabled = processor.is_cache_enabled()
    logger.info(f"Cache aktiviert: {is_cache_enabled}")
    
    if not is_cache_enabled:
        logger.error("Cache ist nicht aktiviert, Test abgebrochen")
        return False
    
    # Prüfe, ob die Cache-Collection gesetzt ist
    logger.info(f"Cache-Collection: {processor.cache_collection_name}")
    
    # Erstelle Cache-Key für die Testdatei
    cache_key = processor._create_cache_key(str(test_file))
    logger.info(f"Cache-Key: {cache_key}")
    
    # Testdaten für Verarbeitung
    source_info = {
        "original_filename": f"test_{uuid.uuid4()}.mp3",
        "video_id": None
    }
    
    # Prüfe, ob der Eintrag bereits im Cache ist (sollte nicht sein)
    cache_hit, _ = processor.get_from_cache(cache_key)
    if cache_hit:
        logger.info("Lösche vorhandenen Cache-Eintrag...")
        processor.invalidate_cache(cache_key)
    
    # Erster Durchlauf - sollte verarbeitet und im Cache gespeichert werden
    logger.info("Erster Durchlauf - Verarbeitung und Caching...")
    try:
        # Setze Whisper-Transcriber-Mock
        processor.transcriber = MockWhisperTranscriber(processor)
        
        # Setze Transformer-Mock
        processor.transformer = MockTransformerProcessor()
        
        # Verarbeite Audio
        first_result = await processor.process(
            audio_source=str(test_file),
            source_info=source_info,
            source_language="de",
            target_language="en",
            use_cache=True
        )
        
        logger.info(f"Erstes Ergebnis - Aus Cache: {first_result.process.is_from_cache}")
        
        # Prüfe, ob das Ergebnis nicht aus dem Cache kam
        assert not first_result.process.is_from_cache, "Erstes Ergebnis sollte nicht aus dem Cache kommen"
        
        # Prüfe, ob das Ergebnis im Cache gespeichert wurde
        cache_hit, cached_result = processor.get_from_cache(cache_key)
        assert cache_hit, "Ergebnis wurde nicht im Cache gespeichert"
        
        logger.info("Erstes Ergebnis erfolgreich verarbeitet und im Cache gespeichert")
        
        # Zweiter Durchlauf - sollte aus dem Cache geladen werden
        logger.info("Zweiter Durchlauf - Laden aus dem Cache...")
        second_result = await processor.process(
            audio_source=str(test_file),
            source_info=source_info,
            source_language="de",
            target_language="en",
            use_cache=True
        )
        
        logger.info(f"Zweites Ergebnis - Aus Cache: {second_result.process.is_from_cache}")
        
        # Prüfe, ob das Ergebnis aus dem Cache kam
        assert second_result.process.is_from_cache, "Zweites Ergebnis sollte aus dem Cache kommen"
        
        logger.info("Zweites Ergebnis erfolgreich aus dem Cache geladen")
        
        # Erfolgsmeldung
        logger.info("MongoDB-Caching für AudioProcessor funktioniert korrekt!")
        return True
        
    except Exception as e:
        logger.error(f"Fehler bei der Verarbeitung: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        # Testdatei löschen
        try:
            os.remove(test_file)
            logger.info(f"Testdatei gelöscht: {test_file}")
        except Exception as e:
            logger.error(f"Fehler beim Löschen der Testdatei: {str(e)}")
        
        # Cache-Eintrag löschen
        try:
            processor.invalidate_cache(cache_key)
            logger.info(f"Cache-Eintrag gelöscht: {cache_key}")
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Cache-Eintrags: {str(e)}")

# Mock-Klassen für Tests

@dataclass
class Chapter:
    """Informationen über ein Kapitel"""
    start: float
    end: float
    title: str
    text: str = ""
    translated_text: str = ""

class TranscriptionResult(TypedDict):
    """Ergebnis der Transkription"""
    segments: List[Dict[str, Any]]
    total_tokens: int
    total_cost: float
    usage: Dict[str, int]

class MockWhisperTranscriber(WhisperTranscriberProtocol):
    """Mock für WhisperTranscriber"""
    
    def __init__(self, processor: Optional[BaseProcessor[Any]] = None):
        self.processor = processor
    
    async def transcribe_segments(
        self, 
        *, 
        segments: List[AudioSegmentInfo] | List[Chapter],
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
    ) -> TranscriptionResult:
        """Mock für transcribe_segments"""
        result_segments: List[TranscriptionSegment] = []
        for i, segment in enumerate(segments):
            result_segments.append(TranscriptionSegment(
                text=f"Testtext {i} für Segment von {segment.start} bis {segment.end}",
                segment_id=i,
                start=segment.start,
                end=segment.end,
                confidence=1.0
            ))
            
        llm_request = LLMRequest(
            model="gpt-3.5-turbo-mock",
            purpose="transcription",
            tokens=100,
            duration=1000.0,
            processor="mock_processor"
        )
        
        llm_model = LLModel(
            model="gpt-3.5-turbo-mock",
            duration=1000.0,
            tokens=100
        )
            
        result = TranscriptionResult(
            text="\n".join(s.text for s in result_segments),
            source_language=source_language,
            segments=result_segments,
            requests=[llm_request] if self.processor else [],
            llms=[llm_model] if self.processor else []
        )
        
        if self.processor:
            self.processor.add_llm_requests([llm_request])
            
        return result

class MockTransformerResponse:
    """Mock für TransformerResponse"""
    
    def __init__(self, text: str, tokens: int, cost: float):
        self.original_text = ""
        self.transformed_text = text
        self.tokens = tokens
        self.cost = cost
        self.model = "gpt-3.5-turbo-mock"

class MockTransformerProcessor:
    """Mock für TransformerProcessor"""
    
    def __init__(self):
        self.model = "gpt-3.5-turbo-mock"
        self.llms = []
    
    def transform(self, source_text: str, source_language: str, target_language: str, context: Optional[Dict[str, Any]] = None) -> MockTransformerResponse:
        """Mock für transform"""
        return MockTransformerResponse(
            text=f"Transformed: {source_text}",
            tokens=len(source_text.split()),
            cost=0.001
        )
    
    def transformByTemplate(self, source_text: str, source_language: str, target_language: str, context: Optional[Dict[str, Any]] = None, template: Optional[str] = None) -> MockTransformerResponse:
        """Mock für transformByTemplate"""
        return MockTransformerResponse(
            text=f"Template transformed: {source_text}",
            tokens=len(source_text.split()),
            cost=0.002
        )

if __name__ == "__main__":
    logger.info("Starte vollständigen AudioProcessor-Cache-Test...")
    
    try:
        asyncio.run(test_audio_processor_with_caching())
        logger.info("Test abgeschlossen")
    except Exception as e:
        logger.error(f"Fehler beim Ausführen des Tests: {str(e)}")
        import traceback
        logger.error(traceback.format_exc()) 