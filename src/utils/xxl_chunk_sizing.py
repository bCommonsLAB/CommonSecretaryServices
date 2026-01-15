"""
XXL Chunk Sizing

Berechnet Chunk-Größe (Zeichen) und Overlap (Zeichen) dynamisch aus
dem Modell-Kontextfenster (Tokens).

Warum Zeichen statt Tokens?
- Tokenisierung ist provider-/modellabhängig und teurer zu berechnen.
- Für eine robuste, einfache Implementierung verwenden wir eine konservative
  Zeichen/Token-Heuristik (ähnlich wie in `src/utils/transcription_utils.py`).

Wichtig:
- Wir bauen Sicherheitsreserven ein (Prompt-Reserve + Response-Reserve),
  damit wir zuverlässig unter dem Kontextlimit bleiben.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True, slots=True)
class XXLChunkSizingConfig:
    """
    Konfiguration für die Chunk-Berechnung.

    Attributes:
        context_length_tokens: Kontextfenster des Modells (Tokens)
        prompt_token_reserve: Reserve für System/User-Prompt-Overhead (Tokens)
        response_token_reserve: Reserve für Modellantwort (Tokens)
        overlap_ratio: Anteil der Chunkgröße für Overlap (z.B. 0.04 = 4%)
        chars_per_token: konservative Heuristik (z.B. 2.5 Zeichen/Token)
        min_chunk_chars: Minimum für chunk_size_chars (Guardrail)
        max_chunk_chars: Maximum für chunk_size_chars (Guardrail)
    """

    context_length_tokens: int
    prompt_token_reserve: int = 8_000
    response_token_reserve: int = 8_000
    overlap_ratio: float = 0.04
    chars_per_token: float = 2.5
    min_chunk_chars: int = 20_000
    max_chunk_chars: int = 2_000_000

    def __post_init__(self) -> None:
        # Strenge, gut dokumentierte Validierung
        if self.context_length_tokens <= 0:
            raise ValueError("context_length_tokens muss > 0 sein")
        if self.prompt_token_reserve < 0:
            raise ValueError("prompt_token_reserve muss >= 0 sein")
        if self.response_token_reserve < 0:
            raise ValueError("response_token_reserve muss >= 0 sein")
        if not (0.0 <= self.overlap_ratio < 1.0):
            raise ValueError("overlap_ratio muss in [0.0, 1.0) liegen")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token muss > 0 sein")
        if self.min_chunk_chars <= 0:
            raise ValueError("min_chunk_chars muss > 0 sein")
        if self.max_chunk_chars < self.min_chunk_chars:
            raise ValueError("max_chunk_chars muss >= min_chunk_chars sein")

        # Reserve darf nicht größer als Kontextfenster sein; sonst bleibt nichts übrig.
        if self.prompt_token_reserve + self.response_token_reserve >= self.context_length_tokens:
            raise ValueError("Reserven sind >= context_length_tokens; es bleibt kein Platz für Input")


@dataclass(frozen=True, slots=True)
class XXLChunkSizingResult:
    """
    Ergebnis der Chunk-Berechnung.

    Attributes:
        chunk_size_chars: Ziel-Chunkgröße in Zeichen
        overlap_chars: Overlap in Zeichen
        available_input_tokens: Tokens, die für Input-Text übrig bleiben
    """

    chunk_size_chars: int
    overlap_chars: int
    available_input_tokens: int

    def __post_init__(self) -> None:
        if self.chunk_size_chars <= 0:
            raise ValueError("chunk_size_chars muss > 0 sein")
        if self.overlap_chars < 0:
            raise ValueError("overlap_chars muss >= 0 sein")
        if self.overlap_chars >= self.chunk_size_chars:
            raise ValueError("overlap_chars muss < chunk_size_chars sein")
        if self.available_input_tokens <= 0:
            raise ValueError("available_input_tokens muss > 0 sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_size_chars": self.chunk_size_chars,
            "overlap_chars": self.overlap_chars,
            "available_input_tokens": self.available_input_tokens,
        }


def compute_xxl_chunk_sizing(cfg: XXLChunkSizingConfig) -> XXLChunkSizingResult:
    """
    Berechnet Chunk-Größe und Overlap.

    Formel:
    - available_input_tokens = context_length_tokens - prompt_reserve - response_reserve
    - chunk_size_chars ~= available_input_tokens * chars_per_token
    - overlap_chars = round(chunk_size_chars * overlap_ratio)

    Guardrails:
    - chunk_size_chars wird in [min_chunk_chars, max_chunk_chars] geklemmt.
    - overlap_chars wird mindestens 0 und höchstens chunk_size_chars-1 geklemmt.
    """

    available_input_tokens = cfg.context_length_tokens - cfg.prompt_token_reserve - cfg.response_token_reserve

    # Grundgröße in Zeichen (konservativ)
    raw_chunk_chars = int(available_input_tokens * cfg.chars_per_token)
    chunk_size_chars = max(cfg.min_chunk_chars, min(cfg.max_chunk_chars, raw_chunk_chars))

    overlap_chars = int(round(chunk_size_chars * cfg.overlap_ratio))
    overlap_chars = max(0, min(chunk_size_chars - 1, overlap_chars))

    return XXLChunkSizingResult(
        chunk_size_chars=chunk_size_chars,
        overlap_chars=overlap_chars,
        available_input_tokens=available_input_tokens,
    )






