"""
@fileoverview OpenAI Utilities - Helper functions for OpenAI API integration

@description
OpenAI-specific helper functions. This file provides functions used for interacting
with the OpenAI API, particularly for structured outputs with Pydantic models.

Main functionality:
- get_structured_gpt: Performs GPT requests with structured outputs
- Dynamic Pydantic model creation based on template definitions
- LLM request tracking for cost analysis
- Validation of GPT responses against schema

Features:
- Template-based structured outputs
- Dynamic Pydantic model creation at runtime
- Function calling for structured data extraction
- LLM tracking integration

@module utils.openai_utils

@exports
- get_structured_gpt(): tuple[BaseModel, Dict, LLMRequest] - Structured GPT request

@usedIn
- src.processors.transformer_processor: Uses get_structured_gpt for template transformation
- All processors requiring structured LLM outputs

@dependencies
- External: openai - OpenAI Python SDK
- External: pydantic - Data validation and model creation
- Internal: src.utils.logger - ProcessingLogger
- Internal: src.core.models.transformer - TemplateFields
- Internal: src.core.models.llm - LLMRequest for tracking
- Internal: src.core.config - Configuration
"""
from typing import Any, Dict, Optional, TypeVar 
import json

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, create_model, Field

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import TemplateFields
from src.core.models.llm import LLMRequest
from src.utils.transcription_utils import WhisperTranscriber
from src.core.config import Config
from src.core.llm import LLMConfigManager, UseCase

T = TypeVar('T', bound=BaseModel)

def get_structured_gpt(
    client: OpenAI,
    template: str,
    field_definitions: TemplateFields,
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4",
    logger: Optional[ProcessingLogger] = None,
    processor: Optional[str] = None
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
        processor: Optional, Name des aufrufenden Processors für LLM-Tracking
        
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
    field_types: Dict[str, Any] = {
        name: (str, Field(
            description=field.description,
            max_length=field.max_length,
            default=field.default,
            title=name.capitalize()
        ))
        for name, field in field_definitions.fields.items()
    }

    # Model erstellen mit expliziter Typisierung
    DynamicTemplateModel: BaseModel = create_model(  # type: ignore
        model_name,
        __base__=BaseModel,
        **field_types
    )

    # LLM-Anfrage senden (mit Provider-Abstraktion)
    llm_config_manager = LLMConfigManager()
    response: Optional[ChatCompletion] = None
    llm_usage: Optional[LLMRequest] = None
    
    try:
        # Versuche Provider für Chat-Completion zu verwenden
        chat_provider = llm_config_manager.get_provider_for_use_case(UseCase.CHAT_COMPLETION)
        if not chat_provider:
            raise ValueError("Provider nicht verfügbar")
        
        chat_model = llm_config_manager.get_model_for_use_case(UseCase.CHAT_COMPLETION) or model
        
        # Verwende Provider
        content, llm_request = chat_provider.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model=chat_model,
            functions=[{
                "name": "extract_template_info",
                "description": "Extrahiert Informationen gemäß Template-Schema",
                "parameters": DynamicTemplateModel.model_json_schema()
            }],
            function_call={"name": "extract_template_info"}
        )
        
        # Für OpenAI-kompatible Provider: Extrahiere function_call aus content
        # Falls der Provider direkt function_call zurückgibt, müssen wir das anders handhaben
        # Hier nehmen wir an, dass der Provider OpenAI-kompatibel ist
        # Für andere Provider müsste die Logik angepasst werden
        result_json_str = content
        llm_usage = llm_request
        
    except Exception as e:
        # Fallback auf direkten Client-Aufruf
        if logger:
            logger.warning(f"Provider nicht verfügbar für get_structured_gpt, verwende Fallback: {str(e)}")
        
        # GPT-4 Anfrage senden
        response = client.chat.completions.create(
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
        
        # GPT-4 Antwort extrahieren
        result_json_str = response.choices[0].message.function_call.arguments
        
        # LLM-Nutzung zentral tracken
        tokens = response.usage.total_tokens if response.usage else 0
        if tokens > 0:  # Nur tracken wenn Tokens verbraucht wurden
            config = Config()
            transcriber_config = config.get('processors', {}).get('transcription', {})
            transcriber = WhisperTranscriber(transcriber_config, processor=None)  # type: ignore
            llm_usage = transcriber.create_llm_request(
                purpose="template_transformation",
                tokens=tokens,
                duration=duration,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger,
                processor=processor or "openai_utils"
            )
        else:
            llm_usage = None
    
    # Validierung und Parsing (für beide Fälle)
    template_model_result: BaseModel = DynamicTemplateModel.model_validate_json(result_json_str)
    result_json: Dict[str, Any] = json.loads(result_json_str)

    return template_model_result, result_json, llm_usage 