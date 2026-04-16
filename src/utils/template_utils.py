"""
@fileoverview Template Utilities - Shared Template-Engine für Template-basierte Extraktion

@description
Wiederverwendbare Funktionen für Template-Verarbeitung. Wird sowohl vom
WhisperTranscriber (Text-Templates) als auch vom ImageAnalyzerProcessor
(Bild-Templates) genutzt.

Funktionen:
- load_template: Template aus Datei oder Content laden
- extract_system_prompt: Systemprompt-Block aus Template extrahieren
- extract_structured_variables: {{name|desc}} Felder parsen
- replace_context_variables: {{key}} Platzhalter ersetzen
- build_extraction_prompt: User-Prompt für LLM bauen (Text oder Bild)
- fill_template_with_data: Template mit extrahierten Daten füllen
- parse_llm_json_response: JSON aus LLM-Antwort parsen

@module utils.template_utils

@usedIn
- src.utils.transcription_utils: WhisperTranscriber delegiert Template-Logik
- src.processors.image_analyzer_processor: ImageAnalyzerProcessor für Bild-Templates
"""

import os
import re
import json
from typing import Dict, Any, Optional, Tuple

from src.core.models.transformer import TemplateField, TemplateFields
from src.utils.logger import ProcessingLogger


# --- Konstanten ---

# Frontmatter-Keys, die als JSON serialisiert werden (Arrays/Objekte)
JSON_FRONTMATTER_KEYS: set[str] = {
    "chapters", "toc", "confidence", "provenance",
    "slides", "attachments", "speakers", "topics", "tags", "affiliations"
}

# Standard-Systemprompt für Text-Analyse
DEFAULT_TEXT_SYSTEM_PROMPT = (
    "You are a precise assistant for text analysis and data extraction. "
    "Analyze the text and extract the requested information. "
    "Provide all answers in the target language ISO 639-1 code:{target_language}. "
    "IMPORTANT: Your response must be a valid JSON object where each key corresponds to a template variable."
)

# Standard-Systemprompt für Bild-Analyse
DEFAULT_IMAGE_SYSTEM_PROMPT = (
    "You are a precise assistant for image analysis and data extraction. "
    "Analyze the image and extract the requested information. "
    "Provide all answers in the target language ISO 639-1 code:{target_language}. "
    "IMPORTANT: Your response must be a valid JSON object where each key corresponds to a template variable."
)


def load_template(
    template_name: Optional[str] = None,
    template_content: Optional[str] = None,
    templates_dir: str = "templates"
) -> str:
    """
    Lädt ein Template aus Datei oder verwendet den übergebenen Inhalt.
    
    Genau eines von template_name oder template_content muss angegeben werden.
    
    Args:
        template_name: Name des Templates (ohne .md)
        template_content: Direkter Template-Inhalt
        templates_dir: Verzeichnis für Template-Dateien
        
    Returns:
        str: Der Template-Inhalt
        
    Raises:
        ValueError: Bei ungültigen Parametern oder fehlender Datei
    """
    if not template_name and not template_content:
        raise ValueError("Entweder template_name oder template_content muss angegeben werden")

    if template_name and template_content:
        raise ValueError("Nur entweder template_name oder template_content darf angegeben werden, nicht beide")

    if template_content:
        return template_content

    if not template_name:
        raise ValueError("Template-Name darf nicht leer sein")

    template_path = os.path.join(templates_dir, f"{template_name}.md")
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise ValueError(f"Template '{template_name}' konnte nicht gelesen werden: {str(e)}")


def extract_system_prompt(
    template_content: str,
    input_type: str = "text"
) -> Tuple[str, str]:
    """
    Extrahiert den Systemprompt aus dem Template-Inhalt.
    
    Sucht nach einem Block '--- systemprompt' im Template. Falls keiner
    vorhanden ist, wird ein Standard-Prompt für den jeweiligen input_type verwendet.
    
    Args:
        template_content: Der Template-Inhalt
        input_type: "text" oder "image" – bestimmt den Standard-Prompt
        
    Returns:
        Tuple[str, str]: (Template ohne Systemprompt, Systemprompt)
    """
    default_prompt = DEFAULT_IMAGE_SYSTEM_PROMPT if input_type == "image" else DEFAULT_TEXT_SYSTEM_PROMPT

    if "--- systemprompt" in template_content:
        parts = template_content.split("--- systemprompt", 1)
        template_without_prompt = parts[0].strip()
        system_prompt = parts[1].strip()

        # JSON-Formatierungsanweisung anhängen
        system_prompt += (
            "\n\nIMPORTANT: Your response must be a valid JSON object "
            "where each key corresponds to a template variable."
        )
        return template_without_prompt, system_prompt

    return template_content, default_prompt


def extract_structured_variables(template_content: str) -> TemplateFields:
    """
    Extrahiert strukturierte Variablen ({{name|beschreibung}}) aus dem Template.
    
    Erkennt sowohl Variablen im YAML-Frontmatter als auch im Body.
    Frontmatter-Variablen werden mit isFrontmatter=True markiert.
    
    Args:
        template_content: Der Template-Inhalt
        
    Returns:
        TemplateFields: Die extrahierten Felder mit Beschreibungen
    """
    pattern = r'\{\{([a-zA-Z][a-zA-Z0-9_]*)\|([^}]+)\}\}'
    matches = list(re.finditer(pattern, template_content))

    seen_vars: set[str] = set()
    field_definitions = TemplateFields(fields={})

    # Extrahiere YAML Frontmatter
    yaml_match = re.search(r'^---\n(.*?)\n---', template_content, re.DOTALL)

    if yaml_match:
        yaml_content = yaml_match.group(1)
        for line in yaml_content.split('\n'):
            line = line.strip()
            if line and ':' in line:
                var_name = line.split(':', 1)[0].strip()
                if var_name and var_name not in seen_vars:
                    seen_vars.add(var_name)
                    # Suche nach Beschreibung in {{name|desc}} Syntax
                    description = "YAML Frontmatter Variable"
                    desc_pattern = r'\{\{' + re.escape(var_name) + r'\|([^}]+)\}\}'
                    desc_match = re.search(desc_pattern, template_content)
                    if desc_match:
                        description = desc_match.group(1).strip()

                    field_definitions.fields[var_name] = TemplateField(
                        description=description,
                        max_length=5000,
                        isFrontmatter=True,
                        default=None
                    )

    # Body-Variablen hinzufügen
    for match in matches:
        var_name = match.group(1).strip()
        if var_name in seen_vars:
            continue
        seen_vars.add(var_name)
        description = match.group(2).strip()

        field_definitions.fields[var_name] = TemplateField(
            description=description,
            max_length=5000,
            default=None,
            isFrontmatter=False
        )

    return field_definitions


def replace_context_variables(
    template_content: str,
    context: Optional[Dict[str, Any]],
    text: str = ""
) -> str:
    """
    Ersetzt einfache Kontext-Variablen ({{key}}) im Template.
    
    Ersetzt {{text}} mit dem übergebenen Text und {{key}} mit Werten aus dem
    Context-Dictionary. Variablen mit Beschreibung ({{key|desc}}) werden hier
    NICHT ersetzt – diese werden vom LLM gefüllt.
    
    Args:
        template_content: Der Template-Inhalt
        context: Dictionary mit Kontext-Variablen
        text: Text für den {{text}}-Platzhalter
        
    Returns:
        str: Template mit ersetzten Variablen
        
    Raises:
        ValueError: Bei Fehlern während der Ersetzung
    """
    if not isinstance(context, dict):
        context = {}

    try:
        # {{text}} Platzhalter ersetzen
        if text:
            template_content = re.sub(r'\{\{text\}\}', lambda _m: text, template_content)

        # Einfache Variablen finden (ohne Description-Teil)
        simple_variables = re.findall(r'\{\{([a-zA-Z][a-zA-Z0-9_]*?)\}\}', template_content)

        for key, value in context.items():
            try:
                if value is not None and key in simple_variables:
                    pat = r'\{\{' + re.escape(str(key)) + r'\}\}'
                    str_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                    template_content = re.sub(pat, (lambda _m, s=str_value: s), template_content)  # type: ignore[misc]
            except Exception as variable_error:
                safe_value = ""
                try:
                    if isinstance(value, (dict, list)):
                        safe_value = json.dumps(value, ensure_ascii=False)[:100]
                    else:
                        safe_value = str(value)[:100]
                except Exception:
                    safe_value = "<Nicht darstellbarer Wert>"
                raise ValueError(
                    f"Fehler beim Ersetzen der Variable '{key}': {variable_error}. "
                    f"Problematischer Wert (gekürzt): {safe_value}"
                )

        return template_content

    except Exception as e:
        if isinstance(e, ValueError) and "Fehler beim Ersetzen der Variable" in str(e):
            raise
        raise ValueError(f"Fehler beim Ersetzen von Kontext-Variablen: {str(e)}")


def get_required_field_descriptions(
    field_definitions: TemplateFields,
    additional_field_descriptions: Optional[Dict[str, str]] = None
) -> Tuple[Dict[str, str], set[str]]:
    """
    Extrahiert die Feldbeschreibungen für den LLM-Prompt.
    
    Filtert reine FrontMatter-Kontext-Felder heraus (die nur aus dem Context
    befüllt werden, nicht vom LLM).
    
    Args:
        field_definitions: Die extrahierten Template-Felder
        additional_field_descriptions: Zusätzliche Feldbeschreibungen
        
    Returns:
        Tuple mit (required_field_descriptions, fm_context_only_set)
    """
    field_descriptions = {
        name: field.description
        for name, field in field_definitions.fields.items()
    }

    # Reine FM-Kontext-Felder identifizieren (nicht vom LLM anfordern)
    fm_context_only: set[str] = {
        name for name, field in field_definitions.fields.items()
        if getattr(field, 'isFrontmatter', False)
        and str(getattr(field, 'description', '')).strip() == "YAML Frontmatter Variable"
    }

    required = {
        name: desc for name, desc in field_descriptions.items()
        if name not in fm_context_only
    }

    if additional_field_descriptions:
        required.update(additional_field_descriptions)

    return required, fm_context_only


def build_extraction_prompt(
    context: Optional[Dict[str, Any]],
    required_field_descriptions: Dict[str, str],
    target_language: str,
    input_type: str = "text"
) -> str:
    """
    Baut den User-Prompt für die LLM-Extraktion.
    
    Erzeugt einen strukturierten Prompt mit CONTEXT, REQUIRED FIELDS und
    INSTRUCTIONS. Bei input_type="text" wird ein {TEXT_PLACEHOLDER} eingefügt,
    bei input_type="image" ein Hinweis auf das beigefügte Bild.
    
    Args:
        context: Kontext-Dictionary
        required_field_descriptions: Felder, die das LLM extrahieren soll
        target_language: Zielsprache (ISO 639-1)
        input_type: "text" oder "image"
        
    Returns:
        str: Der fertige User-Prompt (bei "text" mit {TEXT_PLACEHOLDER})
    """
    context_str = (
        json.dumps(context, indent=2, ensure_ascii=False)
        if isinstance(context, dict) and context
        else "No additional context."
    )

    fields_json = json.dumps(required_field_descriptions, indent=2, ensure_ascii=False)

    if input_type == "image":
        return (
            "Analyze the provided image and extract the information as a JSON object:\n\n"
            f"CONTEXT:\n{context_str}\n\n"
            f"REQUIRED FIELDS:\n{fields_json}\n\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the image carefully and extract all required information\n"
            "2. Return a single JSON object where each key matches a field name\n"
            f"3. Provide all values in language: {target_language}\n"
            "4. Ensure the response is valid JSON\n"
            "5. Do not include any text outside the JSON object\n"
            "6. Only describe what is actually visible in the image"
        )

    # Text-Variante mit Platzhalter
    return (
        "Analyze the following text and extract the information as a JSON object:\n\n"
        "TEXT:\n{TEXT_PLACEHOLDER}\n\n"
        f"CONTEXT:\n{context_str}\n\n"
        f"REQUIRED FIELDS:\n{fields_json}\n\n"
        "INSTRUCTIONS:\n"
        "1. Extract all required information from the text\n"
        "2. Return a single JSON object where each key matches a field name\n"
        f"3. Provide all values in language: {target_language}\n"
        "4. Ensure the response is valid JSON\n"
        "5. Do not include any text outside the JSON object"
    )


def parse_llm_json_response(
    raw_content: str,
    field_definitions: TemplateFields,
    logger: Optional[ProcessingLogger] = None
) -> Dict[str, Any]:
    """
    Parst die LLM-Antwort und extrahiert ein JSON-Objekt.
    
    Verwendet json_validation.extract_and_parse_json als Kernlogik. Bei
    Parse-Fehlern wird ein Fallback-Dict mit Fehlermeldungen erzeugt.
    
    Args:
        raw_content: Roher Text vom LLM
        field_definitions: Erwartete Felder (für Fallback)
        logger: Optionaler Logger
        
    Returns:
        Dict[str, Any]: Geparstes JSON oder Fallback-Dict
    """
    if not raw_content or not raw_content.strip():
        return {
            name: "Leere Antwort vom LLM"
            for name in field_definitions.fields.keys()
        }

    try:
        from src.utils.json_validation import extract_and_parse_json
        return extract_and_parse_json(raw_content)
    except Exception as e:
        if logger:
            logger.error(
                "Ungültiges JSON vom LLM",
                error=e,
                snippet=raw_content[:500]
            )
        return {
            name: f"Fehler bei der Extraktion: {str(e)}"
            for name in field_definitions.fields.keys()
        }


def _serialize_frontmatter_value(field_name: str, value: Any) -> str:
    """
    Serialisiert einen Frontmatter-Wert gemäß strikter YAML-Parser-Regeln.
    
    JSON_FRONTMATTER_KEYS werden als JSON serialisiert, alle anderen als
    gequotete Strings.
    """
    if field_name in JSON_FRONTMATTER_KEYS:
        try:
            return json.dumps(value, ensure_ascii=False, default=lambda o: str(o))
        except Exception:
            return json.dumps(str(value), ensure_ascii=False)

    s = "" if value is None else str(value)
    s = s.replace("\r", " ").replace("\n", " ")
    s = s.replace('"', '\\"')
    return f'"{s}"'


def fill_template_with_data(
    template_content: str,
    result_json: Dict[str, Any],
    field_definitions: TemplateFields,
    context: Optional[Dict[str, Any]] = None,
    fm_context_only: Optional[set[str]] = None,
    fallback_text: str = ""
) -> str:
    """
    Füllt ein Template mit den vom LLM extrahierten Daten.
    
    Ersetzt {{name|desc}}-Platzhalter durch Werte aus result_json. Behandelt
    Frontmatter und Body getrennt mit unterschiedlicher Serialisierung.
    
    Args:
        template_content: Das Template mit Platzhaltern
        result_json: Vom LLM extrahierte Werte
        field_definitions: Template-Felddefinitionen
        context: Optionaler Kontext für FM-Kontext-Felder
        fm_context_only: Set der reinen Kontext-FM-Felder
        fallback_text: Text für verbleibende {{text}}-Platzhalter
        
    Returns:
        str: Das gefüllte Template
    """
    if fm_context_only is None:
        fm_context_only = set()

    # Schritt 1: Ersetze {{name|desc}}-Platzhalter
    for field_name, field_value in result_json.items():
        pattern = r'\{\{' + re.escape(str(field_name)) + r'\|[^}]+\}\}'

        field_def = field_definitions.fields.get(field_name)
        if field_def and getattr(field_def, 'isFrontmatter', False):
            value_str = _serialize_frontmatter_value(field_name, field_value)
        else:
            value_str = "" if field_value is None else str(field_value)

        template_content = re.sub(pattern, (lambda _m, s=value_str: s), template_content)  # type: ignore[misc]

    # Schritt 2: Nackte {{field}}-Platzhalter ersetzen (FM/Body getrennt)
    try:
        fm_match = re.match(r'^---\n(.*?)\n---\n?', template_content, flags=re.DOTALL)
        if fm_match:
            fm_content = fm_match.group(1)
            body_content = template_content[fm_match.end():]

            for k, v in result_json.items():
                simple_pat = r'\{\{' + re.escape(str(k)) + r'\}\}'
                fm_repl = _serialize_frontmatter_value(str(k), v)
                fm_content = re.sub(simple_pat, (lambda _m, s=fm_repl: s), fm_content)  # type: ignore[misc]

                if isinstance(v, (dict, list)):
                    body_repl = json.dumps(v, ensure_ascii=False)
                elif v is None:
                    body_repl = ""
                else:
                    body_repl = str(v)
                body_content = re.sub(simple_pat, (lambda _m, s=body_repl: s), body_content)  # type: ignore[misc]

            template_content = f"---\n{fm_content}\n---" + body_content
        else:
            for k, v in result_json.items():
                simple_pat = r'\{\{' + re.escape(str(k)) + r'\}\}'
                if isinstance(v, (dict, list)):
                    rep = json.dumps(v, ensure_ascii=False)
                elif v is None:
                    rep = ""
                else:
                    rep = str(v)
                template_content = re.sub(simple_pat, (lambda _m, s=rep: s), template_content)  # type: ignore[misc]
    except Exception:
        pass

    # Schritt 3: Deterministischer FrontMatter-Rebuild mit Kontext-Override
    try:
        fm_match3 = re.match(r'^---\n(.*?)\n---\n?(.*)$', template_content, flags=re.DOTALL)
        if fm_match3:
            fm_block = fm_match3.group(1)
            body_part = fm_match3.group(2)

            fm_lines_present = [ln for ln in fm_block.split('\n') if ln.strip()]
            fm_keys: list[str] = []
            for ln in fm_lines_present:
                if ':' in ln:
                    k = ln.split(':', 1)[0].strip()
                    if k and k not in fm_keys:
                        fm_keys.append(k)

            fm_obj: dict[str, Any] = {}
            for k in fm_keys:
                val = result_json.get(k)
                if k in fm_context_only and isinstance(context, dict):
                    val = context.get(k, val)
                elif val is None and isinstance(context, dict):
                    val = context.get(k, val)
                fm_obj[k] = val

            fm_lines_out: list[str] = []
            for k in fm_keys:
                v = fm_obj.get(k)
                if k in JSON_FRONTMATTER_KEYS:
                    fm_lines_out.append(f"{k}: {json.dumps(v, ensure_ascii=False, default=lambda o: str(o))}")
                else:
                    s = "" if v is None else str(v)
                    s = s.replace('"', '\\"').replace("\r", " ").replace("\n", " ")
                    fm_lines_out.append(f'{k}: "{s}"')

            fm_serialized = "---\n" + "\n".join(fm_lines_out) + "\n---\n"
            template_content = fm_serialized + body_part
    except Exception:
        pass

    # Schritt 4: Verbleibende Kontext-Platzhalter ersetzen
    try:
        fm_match_2 = re.match(r'^---\n(.*?)\n---\n?', template_content, flags=re.DOTALL)
        if fm_match_2:
            fm_content_2 = fm_match_2.group(1)
            body_content_2 = template_content[fm_match_2.end():]

            if isinstance(context, dict):
                for k, v in context.items():
                    simple_pat_ctx = r'\{\{' + re.escape(str(k)) + r'\}\}'
                    fm_repl = _serialize_frontmatter_value(str(k), v)
                    fm_content_2 = re.sub(simple_pat_ctx, (lambda _m, s=fm_repl: s), fm_content_2)  # type: ignore[misc]

            body_content_2 = replace_context_variables(body_content_2, context, fallback_text)
            template_content = f"---\n{fm_content_2}\n---\n" + body_content_2
        else:
            template_content = replace_context_variables(template_content, context, fallback_text)
    except Exception:
        template_content = replace_context_variables(template_content, context, fallback_text)

    return template_content


def prepare_template_for_extraction(
    template_name: Optional[str],
    template_content: Optional[str],
    context: Optional[Dict[str, Any]],
    text: str,
    input_type: str = "text",
    templates_dir: str = "templates"
) -> Tuple[str, str, TemplateFields, Dict[str, str], set[str]]:
    """
    Convenience-Funktion: Bereitet ein Template für die LLM-Extraktion vor.
    
    Kombiniert load_template, extract_system_prompt, replace_context_variables
    und extract_structured_variables in einem Aufruf.
    
    Args:
        template_name: Name des Templates
        template_content: Direkter Template-Inhalt
        context: Kontext-Dictionary
        text: Text für {{text}}-Platzhalter (leer bei Bildanalyse)
        input_type: "text" oder "image"
        templates_dir: Verzeichnis für Template-Dateien
        
    Returns:
        Tuple mit (template_content_str, system_prompt, field_definitions,
                    required_field_descriptions, fm_context_only)
                    
    Raises:
        ValueError: Bei ungültigem Template oder fehlenden Variablen
    """
    # 1. Template laden
    raw_content = load_template(template_name, template_content, templates_dir)

    # 2. Systemprompt extrahieren
    cleaned_content, system_prompt = extract_system_prompt(raw_content, input_type)

    # 3. Kontext-Variablen im Body ersetzen (vor LLM)
    fm_split = re.match(r'^---\n(.*?)\n---\n?(.*)$', cleaned_content, flags=re.DOTALL)
    if fm_split:
        fm_head = fm_split.group(1)
        body_part = fm_split.group(2)
        body_part = replace_context_variables(body_part, context, text)
        cleaned_content = f"---\n{fm_head}\n---\n" + body_part
    else:
        cleaned_content = replace_context_variables(cleaned_content, context, text)

    # 4. Strukturierte Variablen extrahieren
    field_definitions = extract_structured_variables(cleaned_content)

    # 5. Required Fields für den Prompt bestimmen
    required_fields, fm_context_only = get_required_field_descriptions(field_definitions)

    return cleaned_content, system_prompt, field_definitions, required_fields, fm_context_only
