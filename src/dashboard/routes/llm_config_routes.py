"""
@fileoverview LLM Config Dashboard Routes - Dashboard routes for LLM configuration management

@description
Dashboard routes for managing LLM provider and use case configuration.
Provides web interface for selecting providers and models per use case.

@module dashboard.routes.llm_config_routes

@exports
- llm_config: Blueprint - Flask blueprint for LLM config dashboard routes
"""

from flask import Blueprint, render_template, request, jsonify
from typing import Any
from pathlib import Path
import yaml

from src.core.llm import LLMConfigManager, UseCase, ProviderManager
from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger

# Create the blueprint
llm_config = Blueprint('llm_config_dashboard', __name__)

# Initialize logger
logger = get_logger(process_id="llm-config-dashboard")


@llm_config.route('/llm-config', methods=['GET'])
def llm_config_page() -> str:
    """
    Zeigt die LLM-Konfigurationsseite an.
    
    Returns:
        str: Rendered template
    """
    try:
        config_manager = LLMConfigManager()
        
        try:
            # Lade alle Provider und Use-Cases
            providers = config_manager.get_all_providers()
            use_cases = config_manager.get_all_use_cases()
            
            # Konvertiere zu Dictionary-Format für Template
            providers_dict = {
                name: {
                    "enabled": config.enabled,
                    "has_api_key": bool(config.api_key and config.api_key != 'not-configured')
                }
                for name, config in providers.items()
            }
            
            use_cases_dict = {
                name: config.to_dict() 
                for name, config in use_cases.items()
            }
            
            # Lade aktuelle Konfiguration für Anzeige
            app_config = Config()
            config_data = app_config.get_all()
            llm_config_data = config_data.get('llm_config', {})
            
            context = {
                'providers': providers_dict,
                'use_cases': use_cases_dict,
                'llm_config': llm_config_data
            }
            
            return render_template('llm_config.html', **context)
        except Exception as e:
            logger.error(f"Fehler beim Laden der LLM-Konfiguration: {str(e)}")
            # Zeige Seite auch bei Fehlern, aber mit Fehlermeldung
            return render_template('llm_config.html', 
                                 error=f"Fehler beim Laden der Konfiguration: {str(e)}",
                                 providers={},
                                 use_cases={},
                                 llm_config={})
    except Exception as e:
        logger.error(f"Fehler beim Laden der LLM-Konfigurationsseite: {str(e)}")
        return render_template('llm_config.html', error=str(e))


@llm_config.route('/llm-config/api/providers', methods=['GET'])
def get_providers_api() -> Any:
    """
    API-Endpoint für Provider-Liste (für AJAX).
    
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
            "data": providers_info
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Provider: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@llm_config.route('/llm-config/api/models', methods=['GET'])
def get_models_api() -> Any:
    """
    API-Endpoint für Modell-Liste (für AJAX).
    
    Query Parameters:
        provider: Name des Providers
        use_case: Name des Use-Cases
        
    Returns:
        JSON: Liste der verfügbaren Modelle
    """
    try:
        provider_name = request.args.get('provider')
        use_case_str = request.args.get('use_case')
        
        if not provider_name or not use_case_str:
            return jsonify({
                "status": "error",
                "message": "Provider und Use-Case Parameter erforderlich"
            }), 400
        
        # Validiere Use-Case-String
        try:
            UseCase(use_case_str)  # Nur zur Validierung
        except ValueError:
            return jsonify({
                "status": "error",
                "message": f"Ungültiger Use-Case: {use_case_str}"
            }), 400
        
        # Lade Provider-Konfiguration
        config_manager = LLMConfigManager()
        provider_config = config_manager.get_provider_config(provider_name)
        
        if not provider_config or not provider_config.enabled:
            return jsonify({
                "status": "error",
                "message": f"Provider '{provider_name}' nicht verfügbar oder deaktiviert"
            }), 404
        
        # Hole verfügbare Modelle direkt aus der Config (ohne Provider-Instanz zu erstellen)
        # Das ermöglicht es, Modelle auch ohne API-Key anzuzeigen
        available_models = provider_config.available_models.get(use_case_str, [])
        
        if not available_models:
            return jsonify({
                "status": "error",
                "message": f"Keine Modelle für Provider '{provider_name}' und Use-Case '{use_case_str}' konfiguriert"
            }), 404
        
        return jsonify({
            "status": "success",
            "data": available_models
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Modelle: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@llm_config.route('/llm-config/api/save', methods=['POST'])
def save_config_api() -> Any:
    """
    Speichert die LLM-Konfiguration in config.yaml.
    
    Request Body:
        use_cases: Dictionary mit Use-Case-Konfigurationen
            {
                "transcription": {"provider": "openai", "model": "whisper-1"},
                "image2text": {"provider": "openai", "model": "gpt-4o"},
                ...
            }
    
    Returns:
        JSON: Erfolgsstatus
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        use_cases_config = data.get('use_cases', {})
        
        if not use_cases_config:
            return jsonify({
                "status": "error",
                "message": "Keine Use-Case-Konfigurationen übergeben"
            }), 400
        
        # Lade aktuelle config.yaml
        config_path = Path(__file__).parents[3] / 'config' / 'config.yaml'
        
        if not config_path.exists():
            return jsonify({
                "status": "error",
                "message": f"Konfigurationsdatei nicht gefunden: {config_path}"
            }), 404
        
        # Lade bestehende Konfiguration
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f) or {}
        
        # Stelle sicher, dass llm_config Sektion existiert
        if 'llm_config' not in config_data:
            config_data['llm_config'] = {}
        
        if 'use_cases' not in config_data['llm_config']:
            config_data['llm_config']['use_cases'] = {}
        
        # Aktualisiere Use-Case-Konfigurationen
        for use_case_name, use_case_data in use_cases_config.items():
            if isinstance(use_case_data, dict) and 'provider' in use_case_data and 'model' in use_case_data:
                config_data['llm_config']['use_cases'][use_case_name] = {
                    'provider': use_case_data['provider'],
                    'model': use_case_data['model']
                }
        
        # Speichere aktualisierte Konfiguration
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        # Lade Konfiguration neu
        config_manager = LLMConfigManager()
        config_manager.reload_config()
        
        logger.info(f"LLM-Konfiguration erfolgreich gespeichert: {use_cases_config}")
        
        return jsonify({
            "status": "success",
            "message": "Konfiguration erfolgreich gespeichert"
        })
    except Exception as e:
        logger.error(f"Fehler beim Speichern der LLM-Konfiguration: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Speichern: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/test', methods=['POST'])
def test_config_api() -> Any:
    """
    Testet die LLM-Konfiguration für einen oder alle Use-Cases.
    
    Request Body (optional):
        use_case: Optional, spezifischer Use-Case zum Testen
        provider: Optional, spezifischer Provider zum Testen
        
    Returns:
        JSON: Testergebnisse
    """
    try:
        data = request.get_json() or {}
        use_case_name = data.get('use_case')
        
        config_manager = LLMConfigManager()
        test_results = []
        
        # Wenn spezifischer Use-Case angegeben, teste nur diesen
        if use_case_name:
            try:
                use_case = UseCase(use_case_name)
                try:
                    provider = config_manager.get_provider_for_use_case(use_case)
                    model = config_manager.get_model_for_use_case(use_case)
                except ProcessingError as pe:
                    # Prüfe ob es ein ImportError ist (fehlendes Paket)
                    error_msg = str(pe)
                    if "nicht installiert" in error_msg or "ImportError" in error_msg or "mistralai" in error_msg.lower():
                        test_results.append({
                            "use_case": use_case_name,
                            "status": "warning",
                            "message": f"Provider-Paket nicht installiert: {error_msg}. Die Konfiguration ist korrekt, aber das Paket muss installiert werden."
                        })
                    else:
                        test_results.append({
                            "use_case": use_case_name,
                            "status": "error",
                            "message": f"Fehler beim Laden des Providers: {error_msg}"
                        })
                    return jsonify({
                        "status": "warning" if "nicht installiert" in error_msg else "error",
                        "results": test_results
                    })
                
                if not provider:
                    test_results.append({
                        "use_case": use_case_name,
                        "status": "error",
                        "message": f"Kein Provider für Use-Case '{use_case_name}' konfiguriert"
                    })
                else:
                    # Prüfe ob Provider den Use-Case unterstützt
                    if hasattr(provider, 'is_use_case_supported'):
                        if not provider.is_use_case_supported(use_case):
                            test_results.append({
                                "use_case": use_case_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "error",
                                "message": f"Provider '{provider.get_provider_name()}' unterstützt Use-Case '{use_case_name}' nicht"
                            })
                            return jsonify({
                                "status": "error",
                                "results": test_results
                            })
                    
                    # Teste einfache Operation
                    try:
                        available_models = provider.get_available_models(use_case)
                        if model in available_models:
                            test_results.append({
                                "use_case": use_case_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "success",
                                "message": f"Konfiguration gültig: {provider.get_provider_name()} / {model}"
                            })
                        else:
                            test_results.append({
                                "use_case": use_case_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "warning",
                                "message": f"Modell '{model}' nicht in verfügbaren Modellen: {available_models}"
                            })
                    except Exception as e:
                        test_results.append({
                            "use_case": use_case_name,
                            "provider": provider.get_provider_name() if provider else "unknown",
                            "model": model or "unknown",
                            "status": "error",
                            "message": f"Fehler beim Testen: {str(e)}"
                        })
            except ValueError:
                test_results.append({
                    "use_case": use_case_name,
                    "status": "error",
                    "message": f"Ungültiger Use-Case: {use_case_name}"
                })
        else:
            # Teste alle Use-Cases
            use_cases = config_manager.get_all_use_cases()
            
            for uc_name in use_cases.keys():
                try:
                    use_case = UseCase(uc_name)
                    try:
                        provider = config_manager.get_provider_for_use_case(use_case)
                        model = config_manager.get_model_for_use_case(use_case)
                    except ProcessingError as pe:
                        # Prüfe ob es ein ImportError ist (fehlendes Paket)
                        error_msg = str(pe)
                        if "nicht installiert" in error_msg or "ImportError" in error_msg or "mistralai" in error_msg.lower():
                            test_results.append({
                                "use_case": uc_name,
                                "status": "warning",
                                "message": f"Provider-Paket nicht installiert: {error_msg}. Die Konfiguration ist korrekt, aber das Paket muss installiert werden."
                            })
                        else:
                            test_results.append({
                                "use_case": uc_name,
                                "status": "error",
                                "message": f"Fehler beim Laden des Providers: {error_msg}"
                            })
                        continue
                    
                    if not provider:
                        test_results.append({
                            "use_case": uc_name,
                            "status": "error",
                            "message": f"Kein Provider für Use-Case '{uc_name}' verfügbar"
                        })
                        continue
                    
                    # Prüfe ob Provider den Use-Case unterstützt
                    if hasattr(provider, 'is_use_case_supported'):
                        if not provider.is_use_case_supported(use_case):
                            test_results.append({
                                "use_case": uc_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "error",
                                "message": f"Provider '{provider.get_provider_name()}' unterstützt Use-Case '{uc_name}' nicht"
                            })
                            continue
                    
                    # Teste ob Modell verfügbar ist
                    try:
                        available_models = provider.get_available_models(use_case)
                        if model in available_models:
                            test_results.append({
                                "use_case": uc_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "success",
                                "message": f"Konfiguration gültig"
                            })
                        else:
                            test_results.append({
                                "use_case": uc_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "warning",
                                "message": f"Modell '{model}' möglicherweise nicht verfügbar"
                            })
                    except Exception as e:
                        test_results.append({
                            "use_case": uc_name,
                            "provider": provider.get_provider_name() if provider else "unknown",
                            "model": model or "unknown",
                            "status": "error",
                            "message": f"Fehler beim Testen: {str(e)}"
                        })
                except Exception as e:
                    test_results.append({
                        "use_case": uc_name,
                        "status": "error",
                        "message": f"Fehler: {str(e)}"
                    })
        
        # Bestimme Gesamtstatus
        all_success = all(r.get('status') == 'success' for r in test_results) if test_results else False
        has_errors = any(r.get('status') == 'error' for r in test_results) if test_results else False
        
        overall_status = "success" if all_success else ("error" if has_errors else "warning")
        
        return jsonify({
            "status": overall_status,
            "results": test_results
        })
    except Exception as e:
        logger.error(f"Fehler beim Testen der LLM-Konfiguration: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Testen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/models-overview', methods=['GET'])
def models_overview_page() -> str:
    """
    Zeigt eine Übersichtsseite aller verfügbaren Modelle pro Provider und Use-Case an.
    
    Returns:
        str: Rendered template
    """
    try:
        return render_template('llm_models_overview.html')
    except Exception as e:
        logger.error(f"Fehler beim Laden der Modell-Übersichtsseite: {str(e)}")
        return render_template('llm_models_overview.html', error=str(e))


