"""
@fileoverview JSON Validation Utility - Zentrale JSON-Extraktion und -Validierung

@description
Zentrale Utility für JSON-Extraktion aus LLM-Antworten und JSON Schema Validierung.
Wird sowohl vom Chat-Endpoint als auch von der Template-Transformation verwendet.

@module utils.json_validation

@exports
- extract_and_parse_json: Extrahiert und parst JSON aus LLM-Antworten
- validate_json_schema: Validiert JSON gegen JSON Schema
- extract_json_from_markdown: Entfernt Markdown-Codeblöcke
- sanitize_json_string: Bereinigt JSON-Strings
"""

import json
import re
from typing import Dict, Any, Optional, Tuple

try:
    import jsonschema
    from jsonschema import validate, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False


class JSONParseError(Exception):
    """Fehler beim Parsen von JSON."""
    pass


class InvalidSchemaError(Exception):
    """Fehler bei ungültigem JSON Schema."""
    pass


class SchemaValidationError(Exception):
    """Fehler bei Schema-Validierung."""
    pass


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
    s = s.lstrip("\ufeff\n\r\t ").rstrip()
    
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


def extract_and_parse_json(content: str) -> Dict[str, Any]:
    """
    Extrahiert und parst JSON aus LLM-Antworten.
    
    Führt folgende Schritte aus:
    1. Entfernt Markdown-Codeblöcke
    2. Versucht direktes JSON-Parsing
    3. Falls fehlgeschlagen: Extrahiert JSON-Substring und sanitized
    4. Versucht erneutes Parsing
    
    Args:
        content: Roher Content-String von LLM
        
    Returns:
        Dict[str, Any]: Geparstes JSON-Objekt
        
    Raises:
        JSONParseError: Wenn JSON nicht geparst werden konnte
    """
    if not content or not content.strip():
        raise JSONParseError("Leerer Content-String")
    
    # Schritt 1: Entferne Markdown-Codeblöcke
    cleaned_content = extract_json_from_markdown(content)
    
    # Schritt 2: Versuche direktes Parsing
    try:
        return json.loads(cleaned_content)
    except json.JSONDecodeError as e_primary:
        # Schritt 3: Extrahiere JSON-Substring und sanitized
        candidate: str = extract_json_substring(cleaned_content) or cleaned_content
        sanitized: str = sanitize_json_string(candidate)
        
        # Schritt 4: Versuche erneutes Parsing
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError as e_secondary:
            raise JSONParseError(
                f"JSON konnte nicht geparst werden. "
                f"Primärer Fehler: {str(e_primary)}, "
                f"Sekundärer Fehler: {str(e_secondary)}, "
                f"Content-Snippet: {sanitized[:500]}"
            ) from e_secondary


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

