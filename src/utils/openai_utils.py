"""
OpenAI-spezifische Hilfsfunktionen.
"""
from typing import Any, Dict, Optional, Type, TypeVar
from dataclasses import dataclass, field
import json

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, create_model, Field

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import TemplateFields
from src.core.models.llm import LLMRequest

T = TypeVar('T', bound=BaseModel)

def get_structured_gpt(
    client: OpenAI,
    template: str,
    field_definitions: TemplateFields,
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4",
    logger: Optional[ProcessingLogger] = None
) -> tuple[BaseModel, Dict[str, Any], LLMRequest]:
    """Erstellt ein Pydantic Model und führt GPT-Anfrage durch.
    
    Args:
        client: OpenAI Client
        template: Name für das dynamische Pydantic Model
        field_definitions: Felddefinitionen für das Model
        system_prompt: System-Prompt für GPT
        user_prompt: User-Prompt für GPT
        model: GPT Modell (default: gpt-4)
        logger: Optional, Logger für Debug-Ausgaben
        
    Returns:
        Tuple aus:
        - Validiertes Model-Ergebnis
        - Rohdaten als Dict
        - LLM-Nutzungsinformationen
    """
    model_name: str = f'Template{template.capitalize()}Model'

    # Zeitmessung starten
    import time
    start_time: float = time.time()

    # Pydantic Model erstellen
    field_types: Dict[str, tuple[Type[str], Any]] = {
        name: (str, Field(
            description=field.description,
            max_length=field.max_length,
            default=field.default,
            title=name.capitalize()
        ))
        for name, field in field_definitions.fields.items()
    }

    # Model erstellen mit expliziter Typisierung
    DynamicTemplateModel = create_model(
        model_name,
        __base__=BaseModel,
        **field_types
    )

    # GPT-4 Anfrage senden
    response: ChatCompletion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        functions=[{
            "name": "extract_template_info",
            "description": "Extrahiert Informationen gemäß Template-Schema",
            "parameters": DynamicTemplateModel.model_json_schema()
        }],
        function_call={"name": "extract_template_info"}
    )

    # Zeitmessung beenden und Dauer in Millisekunden berechnen
    duration: int = int((time.time() - start_time) * 1000)

    if not response.choices or not response.choices[0].message or not response.choices[0].message.function_call:
        raise ValueError("Keine gültige Antwort vom LLM erhalten")

    # GPT-4 Antwort extrahieren und validieren
    result_json_str: str = response.choices[0].message.function_call.arguments
    template_model_result: BaseModel = DynamicTemplateModel.model_validate_json(result_json_str)

    # String in ein Python-Dict umwandeln
    result_json: Dict[str, Any] = json.loads(result_json_str)

    # LLM-Nutzung tracken
    llm_usage: LLMRequest = LLMRequest(
        model=model,
        purpose="template_transformation",
        tokens=response.usage.total_tokens if response.usage else 0,
        duration=duration
    )

    return template_model_result, result_json, llm_usage 