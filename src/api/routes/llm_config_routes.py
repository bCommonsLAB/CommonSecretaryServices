"""
@fileoverview LLM Config Routes - API endpoints for LLM configuration management

@description
API endpoints for managing LLM provider and use case configuration.
Provides endpoints for retrieving and updating LLM configurations.

@module api.routes.llm_config_routes

@exports
- llm_config: Blueprint - Flask blueprint for LLM config routes
"""

from flask import Blueprint, jsonify, request
from typing import Dict, Any, Optional, List

from src.core.llm import LLMConfigManager, UseCase, ProviderManager
from src.utils.logger import get_logger

# Create the blueprint
llm_config = Blueprint('llm_config', __name__)

# Initialize logger
logger = get_logger(process_id="llm-config-api")


@llm_config.route('/api/llm-config', methods=['GET'])
def get_llm_config() -> Any:
    """
    Gibt die aktuelle LLM-Konfiguration zurück.
    
    Returns:
        JSON: Aktuelle Konfiguration mit Providern und Use-Cases
    """
    try:
        config_manager = LLMConfigManager()
        
        # Lade alle Provider und Use-Cases
        providers = config_manager.get_all_providers()
        use_cases = config_manager.get_all_use_cases()
        
        # Konvertiere zu Dictionary-Format
        providers_dict = {
            name: config.to_dict() 
            for name, config in providers.items()
        }
        
        use_cases_dict = {
            name: config.to_dict() 
            for name, config in use_cases.items()
        }
        
        return jsonify({
            "status": "success",
            "data": {
                "providers": providers_dict,
                "use_cases": use_cases_dict
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der LLM-Konfiguration: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Konfiguration: {str(e)}"
        }), 500


@llm_config.route('/api/llm-config/providers', methods=['GET'])
def get_providers() -> Any:
    """
    Gibt alle verfügbaren Provider zurück.
    
    Returns:
        JSON: Liste der verfügbaren Provider
    """
    try:
        provider_manager = ProviderManager()
        available_providers = provider_manager.get_available_providers()
        
        config_manager = LLMConfigManager()
        providers_info = []
        
        for provider_name in available_providers:
            provider_config = config_manager.get_provider_config(provider_name)
            if provider_config:
                providers_info.append({
                    "name": provider_name,
                    "enabled": provider_config.enabled,
                    "has_api_key": bool(provider_config.api_key)
                })
            else:
                providers_info.append({
                    "name": provider_name,
                    "enabled": False,
                    "has_api_key": False
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "providers": providers_info
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Provider: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Provider: {str(e)}"
        }), 500


@llm_config.route('/api/llm-config/models', methods=['GET'])
def get_models() -> Any:
    """
    Gibt verfügbare Modelle für einen Provider und Use-Case zurück.
    
    Query Parameters:
        provider: Name des Providers
        use_case: Name des Use-Cases
        
    Returns:
        JSON: Liste der verfügbaren Modelle
    """
    try:
        provider_name = request.args.get('provider')
        use_case_str = request.args.get('use_case')
        
        if not provider_name:
            return jsonify({
                "status": "error",
                "message": "Provider-Parameter fehlt"
            }), 400
        
        if not use_case_str:
            return jsonify({
                "status": "error",
                "message": "Use-Case-Parameter fehlt"
            }), 400
        
        # Konvertiere Use-Case-String zu Enum
        try:
            use_case = UseCase(use_case_str)
        except ValueError:
            return jsonify({
                "status": "error",
                "message": f"Ungültiger Use-Case: {use_case_str}"
            }), 400
        
        # Lade Provider
        config_manager = LLMConfigManager()
        provider_config = config_manager.get_provider_config(provider_name)
        
        if not provider_config or not provider_config.enabled:
            return jsonify({
                "status": "error",
                "message": f"Provider '{provider_name}' nicht verfügbar oder deaktiviert"
            }), 404
        
        # Erstelle Provider-Instanz
        provider_manager = ProviderManager()
        # Füge available_models zu additional_config hinzu, damit es an Provider übergeben wird
        provider_kwargs = provider_config.additional_config.copy()
        if provider_config.available_models:
            provider_kwargs['available_models'] = provider_config.available_models
        
        provider = provider_manager.get_provider(
            provider_name=provider_name,
            api_key=provider_config.api_key,
            base_url=provider_config.base_url,
            **provider_kwargs
        )
        
        # Hole verfügbare Modelle
        models = provider.get_available_models(use_case)
        
        return jsonify({
            "status": "success",
            "data": {
                "provider": provider_name,
                "use_case": use_case_str,
                "models": models
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Modelle: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Modelle: {str(e)}"
        }), 500


@llm_config.route('/api/llm-config/test', methods=['POST'])
def test_provider() -> Any:
    """
    Testet die Verbindung zu einem Provider.
    
    Request Body:
        provider: Name des Providers
        use_case: Optional, Use-Case zum Testen
        
    Returns:
        JSON: Testergebnis
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        provider_name = data.get('provider')
        if not provider_name:
            return jsonify({
                "status": "error",
                "message": "Provider-Parameter fehlt"
            }), 400
        
        # Lade Provider-Konfiguration
        config_manager = LLMConfigManager()
        provider_config = config_manager.get_provider_config(provider_name)
        
        if not provider_config:
            return jsonify({
                "status": "error",
                "message": f"Provider '{provider_name}' nicht gefunden"
            }), 404
        
        if not provider_config.enabled:
            return jsonify({
                "status": "error",
                "message": f"Provider '{provider_name}' ist deaktiviert"
            }), 400
        
        # Versuche Provider zu erstellen
        try:
            provider_manager = ProviderManager()
            # Füge available_models zu additional_config hinzu, damit es an Provider übergeben wird
            provider_kwargs = provider_config.additional_config.copy()
            if provider_config.available_models:
                provider_kwargs['available_models'] = provider_config.available_models
            
            provider = provider_manager.get_provider(
                provider_name=provider_name,
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                **provider_kwargs
            )
            
            # Teste einfache Operation (falls Use-Case angegeben)
            use_case_str = data.get('use_case')
            if use_case_str:
                try:
                    use_case = UseCase(use_case_str)
                    models = provider.get_available_models(use_case)
                    return jsonify({
                        "status": "success",
                        "message": f"Provider '{provider_name}' ist verfügbar",
                        "data": {
                            "provider": provider_name,
                            "use_case": use_case_str,
                            "available_models": models
                        }
                    })
                except ValueError:
                    pass
            
            return jsonify({
                "status": "success",
                "message": f"Provider '{provider_name}' ist verfügbar"
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Fehler beim Testen des Providers: {str(e)}"
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Testen des Providers: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Testen: {str(e)}"
        }), 500


@llm_config.route('/api/llm-config/presets', methods=['GET'])
def get_presets() -> Any:
    """
    Gibt voreingestellte Konfigurationen zurück.
    Verwendet dynamisch die ersten verfügbaren Modelle aus der config.yaml.
    
    Returns:
        JSON: Liste der voreingestellten Konfigurationen
    """
    try:
        config_manager = LLMConfigManager()
        
        def get_first_model_for_provider_use_case(provider_name: str, use_case: UseCase) -> Optional[str]:
            """
            Gibt das erste verfügbare Modell für einen Provider und Use-Case zurück.
            
            Args:
                provider_name: Name des Providers
                use_case: Use-Case Enum
                
            Returns:
                Optional[str]: Erstes verfügbares Modell oder None
            """
            try:
                provider_config = config_manager.get_provider_config(provider_name)
                if not provider_config or not provider_config.enabled:
                    return None
                
                # Hole verfügbare Modelle aus der Config
                available_models = provider_config.available_models.get(use_case.value, [])
                if available_models:
                    return available_models[0]  # Erstes Modell
                return None
            except Exception as e:
                logger.warning(f"Fehler beim Abrufen des ersten Modells für {provider_name}/{use_case.value}: {str(e)}")
                return None
        
        # Preset-Definitionen: Welche Provider sollen für welche Use-Cases verwendet werden
        preset_definitions: List[Dict[str, Any]] = [
            {
                "name": "OpenAI Standard",
                "description": "Standard-Konfiguration mit OpenAI",
                "provider_mapping": {
                    "transcription": "openai",
                    "image2text": "openai",
                    "ocr_pdf": "openai",
                    "chat_completion": "openai"
                }
            },
            {
                "name": "Mistral OCR",
                "description": "Mistral für OCR, OpenAI für den Rest",
                "provider_mapping": {
                    "transcription": "openai",
                    "image2text": "openai",
                    "ocr_pdf": "mistral",
                    "chat_completion": "openai"
                }
            },
            {
                "name": "OpenRouter Test",
                "description": "OpenRouter für Chat-Completion",
                "provider_mapping": {
                    "transcription": "openai",
                    "image2text": "openai",
                    "ocr_pdf": "mistral",
                    "chat_completion": "openrouter"
                }
            }
        ]
        
        # Generiere Presets dynamisch
        presets: List[Dict[str, Any]] = []
        for preset_def in preset_definitions:
            preset_config: Dict[str, Dict[str, str]] = {}
            preset_valid = True
            
            provider_mapping: Dict[str, str] = preset_def.get("provider_mapping", {})
            for use_case_name, provider_name in provider_mapping.items():
                try:
                    use_case = UseCase(use_case_name)
                    first_model = get_first_model_for_provider_use_case(provider_name, use_case)
                    
                    if first_model:
                        preset_config[use_case_name] = {
                            "provider": provider_name,
                            "model": first_model
                        }
                    else:
                        logger.warning(
                            f"Kein Modell für Preset '{preset_def['name']}' / "
                            f"Use-Case '{use_case_name}' / Provider '{provider_name}' verfügbar"
                        )
                        preset_valid = False
                        break
                except ValueError:
                    logger.warning(f"Ungültiger Use-Case: {use_case_name}")
                    preset_valid = False
                    break
            
            # Füge Preset nur hinzu, wenn alle Use-Cases konfiguriert werden konnten
            if preset_valid and preset_config:
                presets.append({
                    "name": preset_def["name"],
                    "description": preset_def["description"],
                    "config": preset_config
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "presets": presets
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Presets: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Presets: {str(e)}"
        }), 500


@llm_config.route('/api/llm-config/available-models', methods=['GET'])
def get_available_models_overview() -> Any:
    """
    Gibt eine Übersicht aller verfügbaren Modelle pro Provider und Use-Case zurück.
    
    Returns:
        JSON: Übersicht der verfügbaren Modelle
    """
    try:
        provider_manager = ProviderManager()
        config_manager = LLMConfigManager()
        
        # Hole alle registrierten Provider
        registered_providers = provider_manager.get_available_providers()
        
        # Übersicht erstellen
        overview: Dict[str, Dict[str, List[str]]] = {}
        
        for provider_name in registered_providers:
            provider_config = config_manager.get_provider_config(provider_name)
            
            if not provider_config:
                continue
            
            # Erstelle Provider-Instanz für Modell-Liste
            # Verwende einen gültigen Placeholder-API-Key Format falls nicht konfiguriert
            try:
                api_key = provider_config.api_key
                if not api_key or api_key == 'not-configured':
                    # Verwende Provider-spezifische Placeholder-API-Keys
                    if provider_name == 'openai':
                        api_key = 'sk-placeholder123456789012345678901234567890'
                    elif provider_name == 'mistral':
                        api_key = 'mistral-placeholder123456789012345678901234567890'
                    elif provider_name == 'openrouter':
                        api_key = 'sk-or-placeholder123456789012345678901234567890'
                    else:
                        api_key = 'placeholder-key'
                
                # Füge available_models zu additional_config hinzu, damit es an Provider übergeben wird
                provider_kwargs = provider_config.additional_config.copy()
                if provider_config.available_models:
                    provider_kwargs['available_models'] = provider_config.available_models
                
                provider = provider_manager.get_provider(
                    provider_name=provider_name,
                    api_key=api_key,
                    base_url=provider_config.base_url,
                    **provider_kwargs
                )
            except Exception as e:
                logger.warning(f"Konnte Provider '{provider_name}' nicht initialisieren: {str(e)}")
                continue
            
            # Hole Modelle für jeden Use-Case
            provider_models: Dict[str, List[str]] = {}
            
            for use_case in UseCase:
                try:
                    models = provider.get_available_models(use_case)
                    if models:
                        provider_models[use_case.value] = models
                except Exception as e:
                    logger.warning(f"Fehler beim Abrufen der Modelle für {provider_name}/{use_case.value}: {str(e)}")
                    continue
            
            if provider_models:
                overview[provider_name] = provider_models
        
        return jsonify({
            "status": "success",
            "data": {
                "overview": overview,
                "use_cases": [uc.value for uc in UseCase]
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Modell-Übersicht: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Modell-Übersicht: {str(e)}"
        }), 500


