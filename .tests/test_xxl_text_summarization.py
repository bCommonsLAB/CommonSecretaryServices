import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from src.core.models.llm import LLMRequest
from src.core.models.audio import TranscriptionResult
from src.core.llm.use_cases import UseCase
from src.utils.text_chunking import chunk_text_by_chars
from src.utils.xxl_text_summarization import summarize_xxl_text


class FakeProvider:
    """
    Minimaler Fake-Provider für Tests.
    Simuliert parallel laufende Calls und erzeugt LLMRequest-Objekte.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls: List[List[Dict[str, str]]] = []

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: object,
    ) -> Tuple[str, LLMRequest]:
        # kurze Sleep-Phase, damit Parallelität messbar wird
        self.calls.append(messages)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.02)
            # Erzeuge Content so, dass Mindestlängen getestet werden können.
            user_text = messages[-1]["content"]
            # Wir reagieren auf den Prompt-Hinweis zur Länge (keine harte Enforcement-Logik).
            m = re.search(
                r"(?:Mindestlänge|Ziel-Länge|Anforderung): (?:schreibe )?mindestens (\d+) Zeichen",
                user_text,
            )
            min_len = int(m.group(1)) if m else 0
            if min_len > 0:
                content = ("A" * min_len) + " END"
            else:
                content = f"SUMMARY({len(user_text)})"
            req = LLMRequest(
                model=model,
                purpose="chat_completion",
                tokens=1,
                duration=1.0,
                processor="FakeProvider",
            )
            return content, req
        finally:
            with self._lock:
                self.active -= 1

    # --- Protocol-Stubs (nicht genutzt in diesem Test) ---
    def get_provider_name(self) -> str:
        return "fake"

    def get_client(self) -> Any:
        return None

    def transcribe(
        self,
        audio_data: bytes | Path,
        model: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> tuple[TranscriptionResult, LLMRequest]:
        raise ValueError("FakeProvider unterstützt transcribe() nicht")

    def vision(
        self,
        image_data: bytes,
        prompt: str,
        model: str,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> tuple[str, LLMRequest]:
        raise ValueError("FakeProvider unterstützt vision() nicht")

    def get_available_models(self, use_case: UseCase) -> List[str]:
        return []

    def embedding(
        self,
        texts: List[str],
        model: str,
        input_type: str = "document",
        dimensions: Optional[int] = None,
        **kwargs: Any,
    ) -> tuple[List[List[float]], LLMRequest]:
        raise ValueError("FakeProvider unterstützt embedding() nicht")

    def is_use_case_supported(self, use_case: UseCase) -> bool:
        return use_case == UseCase.CHAT_COMPLETION


def test_summarize_xxl_text_orders_chunks_and_tracks_requests() -> None:
    text = "A" * 1000
    chunks = chunk_text_by_chars(text=text, chunk_size_chars=400, overlap_chars=40)
    provider = FakeProvider()

    res = summarize_xxl_text(
        provider=provider,
        model="google/gemini-2.5-flash",
        chunks=chunks,
        target_language="de",
        max_parallel=2,
        detail_level="high",
        instructions="Bitte extrem genau zusammenfassen und alle Entscheidungen nennen.",
        prompt_use_case="cursor_chat_analysis",
        min_chunk_summary_chars=5000,
        min_final_summary_chars=5000,
    )

    # chunk_count Summaries + 1 final summary
    assert len(res.chunk_summaries) == len(chunks)
    assert len(res.llm_requests) == len(chunks) + 1

    # Reihenfolge stabil: chunk_index aufsteigend
    assert [c.chunk_index for c in res.chunk_summaries] == list(range(len(chunks)))

    # Parallelität wurde begrenzt
    assert provider.max_active <= 2

    # Zusatz-Anweisungen wurden in Prompts übernommen (mind. ein Chunk-Call)
    assert any(
        "Zusätzliche Anweisungen" in call[-1]["content"] and "Bitte extrem genau" in call[-1]["content"]
        for call in provider.calls
    )

    # Mindestlängen sind ein Prompt-Hinweis (keine Garantie ohne Retries).
    assert any("Anforderung: schreibe mindestens 5000 Zeichen" in call[-1]["content"] for call in provider.calls)


