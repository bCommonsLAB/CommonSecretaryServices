"""
XXL Text Summarization (Map-Reduce)

Dieses Modul orchestriert die Zusammenfassung sehr großer Texte:
- Text wird bereits extern in Chunks zerlegt (siehe `src/utils/text_chunking.py`)
- Pro Chunk wird eine Abschnittszusammenfassung erzeugt ("map")
- Aus allen Abschnittszusammenfassungen wird eine finale Zusammenfassung erzeugt ("reduce")

Wichtig:
- Implementierung ist bewusst einfach gehalten (keine Retry- oder Resume-Logik).
- Parallelität ist optional und wird auf max. 3 begrenzt (Kosten/Rate-Limit/Robustheit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.core.llm.protocols import LLMProvider
from src.core.models.llm import LLMRequest
from src.utils.text_chunking import TextChunk


def _use_case_guidance(prompt_use_case: str) -> str:
    """
    Liefert zusätzliche Prompt-Instruktionen pro "Prompt-Use-Case".

    Wichtig:
    - Das ist NICHT der LLM-Use-Case (UseCase Enum), sondern eine fachliche Prompt-Schablone
      für unterschiedliche Zusammenfassungs-Ziele.
    """
    if prompt_use_case == "cursor_chat_analysis":
        return (
            "- Ignoriere Codeblöcke (```...```).\n"
            "- Fokus: Fragen und Antworten (Q/A), Entscheidungen, Trade-offs, Fehler + Fixes.\n"
            "- Strukturiere am Ende explizit:\n"
            "  1) Geplant\n"
            "  2) Umgesetzt\n"
            "  3) Offen / Nächste Schritte\n"
        )
    return ""


def _min_length_guidance(min_chars: int) -> str:
    if min_chars <= 0:
        return ""
    # WICHTIG: Wir erzwingen es nicht im Code (keine Retries), aber formulieren es klar
    # als Anforderung an das LLM.
    return f"- Anforderung: schreibe mindestens {min_chars} Zeichen (nicht Wörter).\n"


def build_prompt_templates_without_text(
    *,
    target_language: str,
    detail_level: str,
    instructions: Optional[str],
    prompt_use_case: str,
    min_chunk_summary_chars: int,
    min_final_summary_chars: int,
) -> Dict[str, Any]:
    """
    Liefert Prompt-Templates (ohne Text-Inhalt) für Logging/Debugging.

    Enthält bewusst KEINEN Chunk-Text und KEINE Abschnittszusammenfassungen.
    """
    chunk_system = (
        "Du bist ein präziser Assistent für Text-Zusammenfassungen. "
        "Du fasst Inhalte zusammen, ohne wichtige Fakten zu verlieren."
    )
    final_system = (
        "Du bist ein präziser Assistent für Meta-Zusammenfassungen. "
        "Du erhältst Abschnittszusammenfassungen und erzeugst daraus eine Gesamtsummary."
    )

    use_case_hint = _use_case_guidance(prompt_use_case)

    detail_chunk = ""
    detail_final = ""
    if detail_level == "high":
        detail_chunk = (
            "- Schreibe eine SEHR detaillierte Zusammenfassung.\n"
            "- Bewahre alle relevanten Fakten, Zahlen, Namen, IDs, Dateinamen, Code-Bezeichner, API-Pfade.\n"
            "- Wenn der Text Entscheidungen, Trade-offs oder Fehlerbehebungen beschreibt: liste sie explizit.\n"
            "- Nutze eine klare Struktur mit Überschriften/Bullets.\n"
        )
        detail_final = (
            "- Schreibe eine SEHR detaillierte Gesamtsummary.\n"
            "- Bewahre alle wichtigen Fakten, Zahlen, Namen, Entscheidungen.\n"
            "- Baue Redundanzen ab, aber lasse keine wichtigen Punkte weg.\n"
            "- Nutze eine klare Struktur mit Überschriften/Bullets.\n"
        )

    instr_block = ""
    if instructions and instructions.strip():
        instr_block = f"\nZusätzliche Anweisungen:\n{instructions.strip()}\n"

    chunk_user_template = (
        "Aufgabe: Fasse den folgenden Textabschnitt {chunk_index_plus_1}/{chunk_count} zusammen.\n"
        f"- Sprache der Ausgabe: {target_language}\n"
        "- Ignoriere redundante Informationen durch Overlap, vermeide Wiederholungen.\n"
        f"{use_case_hint}"
        f"{detail_chunk}"
        f"{_min_length_guidance(min_chunk_summary_chars)}"
        "- Gib NUR die Zusammenfassung zurück, ohne Meta-Kommentare.\n\n"
        f"{instr_block}"
        "TEXTABSCHNITT:\n"
        "{TEXT}"
    )

    final_user_template = (
        "Aufgabe: Erzeuge aus den Abschnittszusammenfassungen eine konsistente, "
        "gut lesbare Gesamtsummary.\n"
        f"- Sprache der Ausgabe: {target_language}\n"
        "- Vermeide Wiederholungen.\n"
        f"{use_case_hint}"
        f"{detail_final}"
        "- Bewahre die wichtigsten Fakten, Zahlen und Entscheidungen.\n"
        f"{_min_length_guidance(min_final_summary_chars)}"
        "- Gib NUR die Gesamtsummary zurück, ohne Meta-Kommentare.\n\n"
        f"{instr_block}"
        "ABSCHNITTSZUSAMMENFASSUNGEN:\n"
        "{CHUNK_SUMMARIES}"
    )

    return {
        "chunk": {
            "system": chunk_system,
            "user_template": chunk_user_template,
        },
        "final": {
            "system": final_system,
            "user_template": final_user_template,
        },
    }


@dataclass(frozen=True, slots=True)
class ChunkSummary:
    """
    Ergebnis einer Chunk-Zusammenfassung.
    """

    chunk_index: int
    start: int
    end: int
    summary_text: str

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index muss >= 0 sein")
        if self.start < 0 or self.end < 0 or self.end < self.start:
            raise ValueError("ungültige start/end Werte")
        if not self.summary_text.strip():
            raise ValueError("summary_text darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "start": self.start,
            "end": self.end,
            "summary_text": self.summary_text,
        }


@dataclass(frozen=True, slots=True)
class XXLTextSummarizationResult:
    """
    Gesamtergebnis der XXL-Zusammenfassung.
    """

    final_summary: str
    chunk_summaries: List[ChunkSummary]
    llm_requests: List[LLMRequest]

    def __post_init__(self) -> None:
        if not self.final_summary.strip():
            raise ValueError("final_summary darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_summary": self.final_summary,
            "chunk_summaries": [c.to_dict() for c in self.chunk_summaries],
            "llm_requests": [r.to_dict() for r in self.llm_requests],
        }


def _build_chunk_messages(
    chunk: TextChunk,
    target_language: str,
    chunk_count: int,
    detail_level: str,
    instructions: Optional[str],
    prompt_use_case: str,
    min_summary_chars: int,
) -> List[Dict[str, str]]:
    system_msg = (
        "Du bist ein präziser Assistent für Text-Zusammenfassungen. "
        "Du fasst Inhalte zusammen, ohne wichtige Fakten zu verlieren." 
    )

    # Detail-Level steuert die Granularität. "high" ist für möglichst genaue Summaries gedacht.
    detail_hint = ""
    if detail_level == "high":
        detail_hint = (
            "- Schreibe eine SEHR detaillierte Zusammenfassung.\n"
            "- Bewahre alle relevanten Fakten, Zahlen, Namen, IDs, Dateinamen, Code-Bezeichner, API-Pfade.\n"
            "- Wenn der Text Entscheidungen, Trade-offs oder Fehlerbehebungen beschreibt: liste sie explizit.\n"
            "- Nutze eine klare Struktur mit Überschriften/Bullets.\n"
        )

    use_case_hint = _use_case_guidance(prompt_use_case)
    min_len_hint = _min_length_guidance(min_summary_chars)

    extra_instructions = ""
    if instructions and instructions.strip():
        extra_instructions = f"\nZusätzliche Anweisungen:\n{instructions.strip()}\n"

    # Hinweis zur Überlappung: Chunk enthält ggf. redundanten Kontext.
    user_msg = (
        f"Aufgabe: Fasse den folgenden Textabschnitt {chunk.index + 1}/{chunk_count} zusammen.\n"
        f"- Sprache der Ausgabe: {target_language}\n"
        "- Ignoriere redundante Informationen durch Overlap, vermeide Wiederholungen.\n"
        f"{use_case_hint}"
        f"{detail_hint}"
        f"{min_len_hint}"
        "- Gib NUR die Zusammenfassung zurück, ohne Meta-Kommentare.\n\n"
        f"{extra_instructions}"
        "TEXTABSCHNITT:\n"
        f"{chunk.text}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _build_final_messages(
    chunk_summaries: List[ChunkSummary],
    target_language: str,
    detail_level: str,
    instructions: Optional[str],
    prompt_use_case: str,
    min_summary_chars: int,
) -> List[Dict[str, str]]:
    system_msg = (
        "Du bist ein präziser Assistent für Meta-Zusammenfassungen. "
        "Du erhältst Abschnittszusammenfassungen und erzeugst daraus eine Gesamtsummary."
    )

    detail_hint = ""
    if detail_level == "high":
        detail_hint = (
            "- Schreibe eine SEHR detaillierte Gesamtsummary.\n"
            "- Bewahre alle wichtigen Fakten, Zahlen, Namen, Entscheidungen.\n"
            "- Baue Redundanzen ab, aber lasse keine wichtigen Punkte weg.\n"
            "- Nutze eine klare Struktur mit Überschriften/Bullets.\n"
        )

    use_case_hint = _use_case_guidance(prompt_use_case)
    min_len_hint = _min_length_guidance(min_summary_chars)

    extra_instructions = ""
    if instructions and instructions.strip():
        extra_instructions = f"\nZusätzliche Anweisungen:\n{instructions.strip()}\n"

    summaries_text = "\n\n".join(
        [f"ABSCHNITT {cs.chunk_index + 1}:\n{cs.summary_text}" for cs in chunk_summaries]
    )

    user_msg = (
        "Aufgabe: Erzeuge aus den Abschnittszusammenfassungen eine konsistente, "
        "gut lesbare Gesamtsummary.\n"
        f"- Sprache der Ausgabe: {target_language}\n"
        "- Vermeide Wiederholungen.\n"
        f"{use_case_hint}"
        f"{detail_hint}"
        "- Bewahre die wichtigsten Fakten, Zahlen und Entscheidungen.\n"
        f"{min_len_hint}"
        "- Gib NUR die Gesamtsummary zurück, ohne Meta-Kommentare.\n\n"
        f"{extra_instructions}"
        "ABSCHNITTSZUSAMMENFASSUNGEN:\n"
        f"{summaries_text}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def summarize_xxl_text(
    *,
    provider: LLMProvider,
    model: str,
    chunks: List[TextChunk],
    target_language: str,
    max_parallel: int = 3,
    detail_level: str = "normal",
    instructions: Optional[str] = None,
    prompt_use_case: str = "general",
    min_chunk_summary_chars: int = 5000,
    min_final_summary_chars: int = 5000,
    temperature: float = 0.2,
    chunk_max_tokens: Optional[int] = 4096,
    final_max_tokens: Optional[int] = 4096,
) -> XXLTextSummarizationResult:
    """
    Führt Map-Reduce Summarization durch.

    Parallelität:
    - `max_parallel` wird auf 1..3 geklemmt.
    - ThreadPool ist bewusst gewählt, da Provider-Calls blocking sind.
    """

    if not chunks:
        raise ValueError("chunks darf nicht leer sein")
    if not target_language.strip():
        raise ValueError("target_language darf nicht leer sein")
    if detail_level not in {"normal", "high"}:
        raise ValueError("detail_level muss 'normal' oder 'high' sein")
    if prompt_use_case not in {"general", "cursor_chat_analysis"}:
        raise ValueError("prompt_use_case muss 'general' oder 'cursor_chat_analysis' sein")
    if min_chunk_summary_chars < 0 or min_final_summary_chars < 0:
        raise ValueError("min_*_summary_chars muss >= 0 sein")

    # Clamp max_parallel (explizit, damit API konsistent bleibt)
    if max_parallel < 1:
        max_parallel = 1
    if max_parallel > 3:
        max_parallel = 3

    llm_requests: List[LLMRequest] = []

    def _summarize_one_chunk(chunk: TextChunk) -> Tuple[ChunkSummary, List[LLMRequest]]:
        summary_text: str = ""
        local_reqs: List[LLMRequest] = []

        # Genau 1 Call pro Chunk (keine Retries), um Kosten stabil zu halten.
        messages = _build_chunk_messages(
            chunk=chunk,
            target_language=target_language,
            chunk_count=len(chunks),
            detail_level=detail_level,
            instructions=instructions,
            prompt_use_case=prompt_use_case,
            min_summary_chars=min_chunk_summary_chars,
        )
        summary_text, llm_req = provider.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=chunk_max_tokens,
        )
        local_reqs.append(llm_req)

        return (
            ChunkSummary(
                chunk_index=chunk.index,
                start=chunk.start,
                end=chunk.end,
                summary_text=summary_text.strip() or "(leer)",
            ),
            local_reqs,
        )

    # Map-Phase (Chunk Summaries)
    chunk_summaries: List[ChunkSummary] = []
    if max_parallel == 1 or len(chunks) == 1:
        for c in chunks:
            cs, reqs = _summarize_one_chunk(c)
            chunk_summaries.append(cs)
            llm_requests.extend(reqs)
    else:
        # Begrenzte Parallelität
        with ThreadPoolExecutor(max_workers=max_parallel) as ex:
            futures = [ex.submit(_summarize_one_chunk, c) for c in chunks]
            for fut in as_completed(futures):
                cs, reqs = fut.result()
                chunk_summaries.append(cs)
                llm_requests.extend(reqs)

        # Reihenfolge stabilisieren
        chunk_summaries.sort(key=lambda x: x.chunk_index)

    # Reduce-Phase (Final Summary)
    final_text: str = ""
    final_reqs: List[LLMRequest] = []
    # Genau 1 Call für die Gesamtsummary (keine Retries), um Kosten stabil zu halten.
    final_messages = _build_final_messages(
        chunk_summaries=chunk_summaries,
        target_language=target_language,
        detail_level=detail_level,
        instructions=instructions,
        prompt_use_case=prompt_use_case,
        min_summary_chars=min_final_summary_chars,
    )
    final_text, final_req = provider.chat_completion(
        messages=final_messages,
        model=model,
        temperature=temperature,
        max_tokens=final_max_tokens,
    )
    final_reqs.append(final_req)

    llm_requests.extend(final_reqs)

    return XXLTextSummarizationResult(
        final_summary=final_text.strip() or "(leer)",
        chunk_summaries=chunk_summaries,
        llm_requests=llm_requests,
    )


