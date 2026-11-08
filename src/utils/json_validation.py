"""
@fileoverview JSON Validation Utility - Zentrale JSON-Extraktion und -Validierung

@description
Zentrale Utility für JSON-Extraktion aus LLM-Antworten und JSON Schema Validierung.
Wird sowohl vom Chat-Endpoint als auch von der Template-Transformation verwendet.

Parse-Stufen (``parse_llm_json``):
1. Markdown-Codezäune entfernen, direkt parsen (``stage = "direct"``).
2. JSON-Substring suchen, ``sanitize_json_string`` (trailing Kommas, ungültige
   Escapes), erneut parsen (``stage = "sanitized"``).
3. Strukturgeführtes Maskieren von geraden Anführungszeichen, rohen Steuerzeichen
   und kaputten Escapes in String-Werten (``escape_unescaped_in_strings``,
   ``stage = "escaped_quotes"``) — das Fehlerbild der Vorlage ``chatverlauf-de``.
4. Reparatur mit der Bibliothek ``json_repair`` (offene Strings, fehlende Kommas,
   sonstige Schäden); das Ergebnis muss ein nicht-leeres Objekt sein
   (``stage = "json_repair"``).

Stufe 2 bis 4 verändern den Inhalt; das Ergebnis trägt dann ``repaired = True``.
Eine Antwort, die nicht mit ``}`` endet, gilt als abgeschnitten und bleibt ein Fehler.
Scheitert auch Stufe 4, fliegt ``JSONParseError`` mit Zeile/Spalte des ersten
Fehlers. Ist ``LLM_JSON_DEBUG_DIR`` gesetzt, landet die vollständige Rohantwort
vorher als Datei dort, und der Pfad steht in der Fehlermeldung (Befund 05.11.2026:
Gemini liefert bei langen ``*_md``-Feldern unmaskierte gerade Anführungszeichen).

@module utils.json_validation

@exports
- parse_llm_json: Parst LLM-Antworten mit Reparaturstufen, meldet ob repariert
- extract_and_parse_json: Kompatibler Wrapper, liefert nur das Objekt
- JSONParseOutcome: Ergebnis von parse_llm_json
- JSONParseError: Fehler mit Zeile/Spalte und Pfad der Rohantwort
- validate_json_schema: Validiert JSON gegen JSON Schema
- extract_json_from_markdown: Entfernt Markdown-Codeblöcke
- sanitize_json_string: Bereinigt JSON-Strings
- escape_unescaped_in_strings: Maskiert Anführungszeichen/Steuerzeichen in Werten
- LLM_JSON_DEBUG_DIR_ENV: Name der Umgebungsvariablen für den Debug-Ordner
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import jsonschema
    from jsonschema import validate, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False

try:
    from json_repair import repair_json as _repair_json
    JSON_REPAIR_AVAILABLE = True
except ImportError:  # pragma: no cover - Abhängigkeit steht in requirements.txt
    _repair_json = None
    JSON_REPAIR_AVAILABLE = False


# Umgebungsvariable: Ordner für Rohantworten, die nicht geparst werden konnten.
# Nicht gesetzt oder leer = aus (Vorgabe). Es wird nur die Modellantwort abgelegt,
# nie Prompt, Eingabetext oder Schlüssel.
LLM_JSON_DEBUG_DIR_ENV = "LLM_JSON_DEBUG_DIR"

# Höchstzahl der Reparatur-Hinweise, die in repair_log übernommen werden
_MAX_REPAIR_LOG_ENTRIES = 20


class JSONParseError(Exception):
    """
    Fehler beim Parsen von JSON.

    Attributes:
        line: Zeile des primären Parse-Fehlers (1-basiert), wenn bekannt
        column: Spalte des primären Parse-Fehlers (1-basiert), wenn bekannt
        dump_path: Pfad der abgelegten Rohantwort, wenn LLM_JSON_DEBUG_DIR gesetzt war
    """

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
        dump_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.line: Optional[int] = line
        self.column: Optional[int] = column
        self.dump_path: Optional[str] = dump_path


class InvalidSchemaError(Exception):
    """Fehler bei ungültigem JSON Schema."""
    pass


class SchemaValidationError(Exception):
    """Fehler bei Schema-Validierung."""
    pass


@dataclass(frozen=True)
class JSONParseOutcome:
    """
    Ergebnis von ``parse_llm_json``.

    Attributes:
        data: Das geparste JSON-Objekt
        repaired: True, wenn der Inhalt vor dem Parsen verändert werden musste
        stage: Stufe, die das Objekt geliefert hat: "direct", "sanitized",
            "escaped_quotes", "json_repair"
        repair_log: Kurze Hinweise, was repariert wurde (gekürzt)
    """
    data: Dict[str, Any]
    repaired: bool = False
    stage: str = "direct"
    repair_log: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.data, dict):
            raise ValueError("data muss ein Dictionary sein")
        if self.stage not in ("direct", "sanitized", "escaped_quotes", "json_repair"):
            raise ValueError(f"Unbekannte Parse-Stufe: {self.stage}")
        if self.stage == "direct" and self.repaired:
            raise ValueError("Stufe 'direct' kann nicht repariert sein")

    def repair_info(self) -> Dict[str, Any]:
        """Kompakte Beschreibung der Reparatur für API-Antworten."""
        return {
            "stage": self.stage,
            "hints": list(self.repair_log),
        }


def extract_json_from_markdown(content: str) -> str:
    """
    Entfernt Markdown-Codeblöcke (```json, ```) aus dem Content.

    Args:
        content: Roher Content-String, möglicherweise mit Markdown-Codeblöcken

    Returns:
        str: Bereinigter Content ohne Markdown-Codeblöcke
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def sanitize_json_string(s: str) -> str:
    """
    Macht typische LLM-Ausgabe zu validerem JSON.

    Fixes:
    - Ungültige Backslash-Escapes: wandelt \\x (x nicht in JSON-Escape) in \\\\x um
    - Entfernt trailing-Kommas vor } oder ]
    - Trimmt unsichtbare BOM/Whitespace

    Args:
        s: JSON-String, der bereinigt werden soll

    Returns:
        str: Bereinigter JSON-String
    """
    # Entferne BOM und trimme
    s = s.lstrip("﻿\n\r\t ").rstrip()

    # Entferne Markdown-Codeblöcke, falls vorhanden
    s = extract_json_from_markdown(s)

    # Entferne trailing Commas wie ,} oder ,]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Ersetze ungültige Backslash-Escapes (alles außer gültigen JSON-Escapes)
    s = re.sub(r"\\(?![\\\"/bfnrtu])", r"\\\\", s)

    return s


def extract_json_substring(text: str) -> Optional[str]:
    """
    Extrahiert den ersten gültigen JSON-Objekt-Substring aus freiem Text.

    Sucht das erste top-level '{' und matching '}' unter Beachtung von Strings und Escapes.
    Gibt None zurück, wenn keine balancierte Struktur gefunden wird.

    Args:
        text: Text, aus dem JSON extrahiert werden soll

    Returns:
        Optional[str]: JSON-Substring oder None
    """
    in_string: bool = False
    escape_next: bool = False
    depth: int = 0
    start_idx: Optional[int] = None

    for idx, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                start_idx = idx
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    return text[start_idx: idx + 1]

    return None


_VALID_SIMPLE_ESCAPES = '"\\/bfnrt'
_KEY_AHEAD_RE = re.compile(r'"[^"\n]{1,120}"\s*:')
_HEX4_RE = re.compile(r"[0-9a-fA-F]{4}")


def escape_unescaped_in_strings(s: str) -> str:
    """
    Maskiert in String-Werten gerade Anführungszeichen, rohe Steuerzeichen und
    ungültige Backslash-Escapes, die ein LLM dort stehen gelassen hat.

    Das ist das Fehlerbild der Vorlage ``chatverlauf-de`` (05.11.2026): lange
    Markdown-Werte mit Zitaten wie ``"Fehler: LLM-JSON (2×)"``. Eine allgemeine
    Reparaturbibliothek liest ``"Fehler: …"`` als neuen Schlüssel und erzeugt
    Phantomfelder; hier entscheidet dagegen die Struktur, ob ein Anführungszeichen
    den String schließt:

    - Schlüssel endet, wenn nach dem Anführungszeichen ``:`` folgt.
    - Wert im Objekt endet vor ``}`` oder vor ``,`` gefolgt vom nächsten Schlüssel
      (``"name":``).
    - Wert im Array endet vor ``]`` oder ``,``.
    - Sonst ist das Anführungszeichen Teil des Textes und wird zu ``\\"``.

    Rohe Zeilenumbrüche, Wagenrückläufe und Tabs in Strings werden zu ``\\n``,
    ``\\r``, ``\\t``; ein Backslash ohne gültiges Escape wird verdoppelt.
    Außerhalb von Strings bleibt der Text unverändert.
    """
    out: List[str] = []
    n = len(s)
    i = 0
    in_string = False
    # Container-Stapel ('{' oder '[') und ob im Objekt gerade ein Schlüssel erwartet wird
    stack: List[str] = []
    expecting_key = False
    string_is_key = False

    def _next_non_ws(pos: int) -> int:
        while pos < n and s[pos] in " \t\r\n":
            pos += 1
        return pos

    while i < n:
        ch = s[i]
        if not in_string:
            if ch == '"':
                in_string = True
                string_is_key = bool(stack) and stack[-1] == "{" and expecting_key
            elif ch in "{[":
                stack.append(ch)
                expecting_key = ch == "{"
            elif ch in "}]":
                if stack:
                    stack.pop()
                expecting_key = False
            elif ch == ":":
                expecting_key = False
            elif ch == ",":
                expecting_key = bool(stack) and stack[-1] == "{"
            out.append(ch)
            i += 1
            continue

        # Innerhalb eines Strings
        if ch == "\\":
            nxt = s[i + 1] if i + 1 < n else ""
            if nxt and nxt in _VALID_SIMPLE_ESCAPES:
                out.append(ch + nxt)
                i += 2
                continue
            if nxt == "u" and _HEX4_RE.fullmatch(s[i + 2:i + 6] or ""):
                out.append(s[i:i + 6])
                i += 6
                continue
            out.append("\\\\")
            i += 1
            continue
        if ch == "\n":
            out.append("\\n")
            i += 1
            continue
        if ch == "\r":
            out.append("\\r")
            i += 1
            continue
        if ch == "\t":
            out.append("\\t")
            i += 1
            continue
        if ch != '"':
            out.append(ch)
            i += 1
            continue

        # Anführungszeichen: schließt es den String?
        j = _next_non_ws(i + 1)
        follower = s[j] if j < n else ""
        closes: bool
        if follower == "":
            closes = True
        elif string_is_key:
            closes = follower == ":"
        elif not stack or stack[-1] == "[":
            closes = follower in ",]}"
        else:  # Wert im Objekt
            if follower == "}":
                closes = True
            elif follower == ",":
                k = _next_non_ws(j + 1)
                closes = k >= n or s[k] == "}" or bool(_KEY_AHEAD_RE.match(s, k))
            elif follower == '"' and _KEY_AHEAD_RE.match(s, j):
                # Nächster Schlüssel ohne Komma davor: Wert schließen, Komma ergänzen,
                # sonst würde der folgende Schlüssel im Wert verschwinden.
                out.append(ch)
                out.append(",")
                in_string = False
                string_is_key = False
                expecting_key = True
                i += 1
                continue
            else:
                closes = False
        if closes:
            in_string = False
            string_is_key = False
        else:
            out.append("\\")
        out.append(ch)
        i += 1

    return "".join(out)


def _looks_truncated(candidate: str) -> bool:
    """
    Erkennt eine mitten im Objekt abgebrochene Antwort (z. B. max_tokens erreicht).

    Eine vollständige Objekt-Antwort endet nach dem Entfernen der Codezäune mit
    ``}``. Fehlt das, würde ``json_repair`` das Objekt still schließen und ein
    unvollständiges Ergebnis als gültig ausgeben. Das bleibt ein Fehler.
    """
    stripped = candidate.rstrip().rstrip("`").rstrip()
    return bool(stripped) and not stripped.endswith("}")


def _location_of(error: json.JSONDecodeError) -> str:
    """Zeile/Spalte eines JSONDecodeError als Text."""
    return f"Zeile {error.lineno}, Spalte {error.colno}"


def _dump_raw_response(
    content: str,
    primary_error: Optional[json.JSONDecodeError],
    label: Optional[str],
    model: Optional[str],
    outcome: str = "failed",
    stage: Optional[str] = None,
) -> Optional[str]:
    """
    Legt die vollständige Rohantwort im Debug-Ordner ab, wenn ``LLM_JSON_DEBUG_DIR``
    gesetzt ist. Liefert den Pfad oder None (aus oder Schreibfehler).

    ``outcome`` ist "failed" (nicht parsebar) oder "repaired" (nur mit Reparatur
    parsebar); beides sind die Fälle, aus denen Fixtures entstehen. Es wird nur die
    Modellantwort gespeichert; Prompt, Eingabetext und Schlüssel gehören nicht hinein.
    """
    debug_dir_str = (os.getenv(LLM_JSON_DEBUG_DIR_ENV) or "").strip()
    if not debug_dir_str:
        return None
    try:
        debug_dir = Path(debug_dir_str)
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label or "llm")[:40] or "llm"
        base = debug_dir / f"{stamp}_{safe_label}_{uuid.uuid4().hex[:8]}"
        raw_path = base.with_suffix(f".{outcome}.txt")
        raw_path.write_text(content, encoding="utf-8")
        meta: Dict[str, Any] = {
            "written_at": stamp,
            "label": label,
            "model": model,
            "outcome": outcome,
            "stage": stage,
            "content_chars": len(content),
            "primary_error": str(primary_error) if primary_error else None,
            "line": primary_error.lineno if primary_error else None,
            "column": primary_error.colno if primary_error else None,
        }
        base.with_suffix(".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(raw_path)
    except OSError:
        return None


def _repair_with_library(candidate: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Stufe 3: ``json_repair``. Liefert (Objekt, Hinweise) oder (None, Hinweise),
    wenn kein nicht-leeres Objekt herauskommt.
    """
    if not JSON_REPAIR_AVAILABLE or _repair_json is None:
        return None, ["json_repair nicht installiert"]
    try:
        repaired_any: Any = _repair_json(candidate, return_objects=True, logging=True)
    except Exception as e:  # json_repair wirft selten, aber nicht nie
        return None, [f"json_repair-Ausnahme: {type(e).__name__}: {e}"]

    repaired_obj: Any = repaired_any
    log_entries: List[Any] = []
    if isinstance(repaired_any, tuple) and len(repaired_any) == 2:
        repaired_obj = repaired_any[0]
        raw_log: Any = repaired_any[1]
        if isinstance(raw_log, list):
            log_entries = list(raw_log)

    hints: List[str] = []
    for entry in log_entries[:_MAX_REPAIR_LOG_ENTRIES]:
        if isinstance(entry, dict):
            text = str(entry.get("text", "")).strip()
            context = str(entry.get("context", "")).strip()
            hints.append(f"{text} [{context}]" if context else text)
        else:
            hints.append(str(entry))
    if len(log_entries) > _MAX_REPAIR_LOG_ENTRIES:
        hints.append(f"... {len(log_entries) - _MAX_REPAIR_LOG_ENTRIES} weitere Hinweise")

    if isinstance(repaired_obj, dict) and repaired_obj:
        return dict(repaired_obj), hints
    return None, hints


def parse_llm_json(
    content: str,
    label: Optional[str] = None,
    model: Optional[str] = None,
) -> JSONParseOutcome:
    """
    Parst eine LLM-Antwort zu einem JSON-Objekt, mit Reparaturstufen.

    Args:
        content: Roher Content-String vom LLM
        label: Kurzer Bezeichner für die Debug-Datei (z. B. Template-Name)
        model: Modellkennung für die Debug-Metadaten

    Returns:
        JSONParseOutcome: Objekt plus Angabe, ob und wie repariert wurde

    Raises:
        JSONParseError: Wenn auch die Reparatur kein gültiges Objekt ergibt. Die
            Meldung nennt Zeile/Spalte des ersten Fehlers und, wenn abgelegt, die
            Datei mit der vollständigen Rohantwort.
    """
    if not content or not content.strip():
        raise JSONParseError("Leerer Content-String")

    # Stufe 1: Codezäune entfernen, direkt parsen
    cleaned_content = extract_json_from_markdown(content)
    try:
        direct: Any = json.loads(cleaned_content)
    except json.JSONDecodeError as e_primary:
        primary_error: json.JSONDecodeError = e_primary
    else:
        if isinstance(direct, dict):
            return JSONParseOutcome(data=direct, repaired=False, stage="direct")
        dump = _dump_raw_response(content, None, label, model)
        raise JSONParseError(
            "JSON ist kein Objekt, sondern "
            f"{type(direct).__name__}" + (f". Rohantwort: {dump}" if dump else ""),
            dump_path=dump,
        )

    def _repaired(outcome: JSONParseOutcome) -> JSONParseOutcome:
        # Reparierte Antworten sind Fixture-Material: mit Debug-Ordner ebenfalls ablegen.
        _dump_raw_response(content, primary_error, label, model, outcome="repaired", stage=outcome.stage)
        return outcome

    # Stufe 2: JSON-Substring und sanitize
    candidate: str = extract_json_substring(cleaned_content) or cleaned_content
    sanitized: str = sanitize_json_string(candidate)
    secondary_error: Optional[json.JSONDecodeError] = None
    try:
        parsed: Any = json.loads(sanitized)
    except json.JSONDecodeError as e_secondary:
        secondary_error = e_secondary
    else:
        if isinstance(parsed, dict):
            return _repaired(JSONParseOutcome(
                data=parsed,
                repaired=True,
                stage="sanitized",
                repair_log=("trailing Kommas oder ungültige Escapes bereinigt",),
            ))

    # Abgeschnittene Antwort: jede weitere Stufe würde das Objekt still schließen.
    truncated = _looks_truncated(cleaned_content)

    # Stufe 3: gerade Anführungszeichen, rohe Steuerzeichen und kaputte Escapes in
    # Werten maskieren — strukturgeführt, deshalb vor der allgemeinen Bibliothek.
    if not truncated:
        escaped = escape_unescaped_in_strings(candidate)
        try:
            parsed_escaped: Any = json.loads(escaped)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed_escaped, dict) and parsed_escaped:
                return _repaired(JSONParseOutcome(
                    data=parsed_escaped,
                    repaired=True,
                    stage="escaped_quotes",
                    repair_log=(
                        "unmaskierte Anführungszeichen, Steuerzeichen oder Escapes in Werten maskiert",
                    ),
                ))

    # Stufe 4: json_repair
    repaired_data: Optional[Dict[str, Any]] = None
    hints: List[str] = []
    if not truncated:
        repaired_data, hints = _repair_with_library(sanitized)
    if repaired_data is not None:
        return _repaired(JSONParseOutcome(
            data=repaired_data,
            repaired=True,
            stage="json_repair",
            repair_log=tuple(hints),
        ))

    # Endgültig gescheitert: Rohantwort ablegen, Fehler mit Ort melden
    dump = _dump_raw_response(content, primary_error, label, model)
    parts: List[str] = [
        "JSON konnte nicht geparst werden.",
        f"Primärer Fehler: {primary_error} ({_location_of(primary_error)}).",
    ]
    if secondary_error is not None:
        parts.append(f"Sekundärer Fehler nach Bereinigung: {secondary_error}.")
    if truncated:
        parts.append("Antwort endet nicht mit '}' — vermutlich abgeschnitten (max_tokens?).")
    elif hints:
        parts.append(f"Reparatur ergab kein Objekt ({len(hints)} Hinweise).")
    else:
        parts.append("Reparatur ergab kein Objekt.")
    parts.append(f"Antwortlänge: {len(content)} Zeichen.")
    if dump:
        parts.append(f"Rohantwort: {dump}")
    else:
        parts.append(f"Content-Snippet: {sanitized[:500]}")
    raise JSONParseError(
        " ".join(parts),
        line=primary_error.lineno,
        column=primary_error.colno,
        dump_path=dump,
    )


def extract_and_parse_json(content: str) -> Dict[str, Any]:
    """
    Extrahiert und parst JSON aus LLM-Antworten (kompatibler Wrapper um
    ``parse_llm_json``; liefert nur das Objekt, ohne Reparatur-Angabe).

    Args:
        content: Roher Content-String von LLM

    Returns:
        Dict[str, Any]: Geparstes JSON-Objekt

    Raises:
        JSONParseError: Wenn JSON nicht geparst werden konnte
    """
    return parse_llm_json(content).data


def validate_json_schema(
    data: Dict[str, Any],
    schema: Dict[str, Any],
    strict: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Validiert JSON gegen JSON Schema.

    Args:
        data: JSON-Daten, die validiert werden sollen
        schema: JSON Schema als Dictionary
        strict: Wenn True, wird bei Validierungsfehler eine Exception geworfen

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
        - is_valid: True wenn Validierung erfolgreich
        - error_message: Fehlermeldung bei Validierungsfehler (None wenn erfolgreich)

    Raises:
        InvalidSchemaError: Wenn das Schema ungültig ist
        SchemaValidationError: Wenn strict=True und Validierung fehlschlägt
    """
    if not JSONSCHEMA_AVAILABLE:
        raise InvalidSchemaError(
            "jsonschema Bibliothek ist nicht verfügbar. "
            "Installiere sie mit: pip install jsonschema"
        )

    # Validiere Schema selbst
    try:
        jsonschema.Draft7Validator.check_schema(schema)
    except jsonschema.SchemaError as e:
        raise InvalidSchemaError(f"Ungültiges JSON Schema: {str(e)}") from e

    # Validiere Daten gegen Schema
    try:
        validate(instance=data, schema=schema)
        return True, None
    except ValidationError as e:
        error_message = f"Schema-Validierung fehlgeschlagen: {e.message}"
        if strict:
            raise SchemaValidationError(error_message) from e
        return False, error_message
