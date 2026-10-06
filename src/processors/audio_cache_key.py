"""
@fileoverview Cache-Schluessel fuer Audio-Ergebnisse - eine Stelle fuer beide Wege

@description
Der Schluessel entscheidet, ob ein frueheres Ergebnis wiederverwendet wird. Alles, was
das Ergebnis aendert, muss hinein: Quelle, Zielsprache, Template, Kontext — und der
MODUS. Ohne den Modus bekaeme /audio/process-diarized das zuvor gecachte Ergebnis von
/audio/process fuer dieselbe Datei (ohne Sprecher) zurueck und umgekehrt.

Reine Funktion, damit sie ohne Processor-Instanz testbar ist.

@module processors.audio_cache_key

@exports
- MODE_PLAIN, MODE_DIARIZED: die beiden Modi
- build_audio_cache_key_base: Baut den Klartext-Schluessel (vor dem Hashen)
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.llm.transcription_context import TranscriptionContext

MODE_PLAIN = "plain"
MODE_DIARIZED = "diarized"
VALID_MODES = frozenset({MODE_PLAIN, MODE_DIARIZED})


def _source_base(audio_path: str, source_info: Optional[Dict[str, Any]]) -> str:
    """Quelle: Video-ID, sonst Originalname, sonst Pfad (+ Groesse, wenn bekannt)."""
    if source_info:
        if source_info.get("video_id"):
            return str(source_info["video_id"])
        if source_info.get("original_filename"):
            return str(source_info["original_filename"])
    try:
        file_size: Optional[int] = Path(audio_path).stat().st_size
    except OSError:
        file_size = None
    return f"{audio_path}_{file_size}" if file_size else audio_path


def build_audio_cache_key_base(
    audio_path: str,
    source_info: Optional[Dict[str, Any]] = None,
    target_language: Optional[str] = None,
    template: Optional[str] = None,
    transcription_context: Optional[TranscriptionContext] = None,
    mode: str = MODE_PLAIN,
) -> str:
    """
    Baut den Klartext-Schluessel. Der Aufrufer hasht ihn (generate_cache_key).

    Der Modus 'plain' schreibt sich NICHT in den Schluessel, damit bestehende
    Cache-Eintraege des normalen Wegs gueltig bleiben. Jeder andere Modus kommt
    ausdruecklich hinein.

    Raises:
        ValueError: bei unbekanntem Modus — kein stiller Rueckfall auf 'plain'
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unbekannter Audio-Modus fuer den Cache-Schluessel: '{mode}'")

    base_key = _source_base(audio_path, source_info)
    if target_language:
        base_key += f"|lang={target_language}"
    if template:
        base_key += f"|template={template}"
    if transcription_context is not None and not transcription_context.is_empty:
        base_key += f"|context={json.dumps(transcription_context.to_dict(), sort_keys=True)}"
    if mode != MODE_PLAIN:
        base_key += f"|mode={mode}"
    return base_key
