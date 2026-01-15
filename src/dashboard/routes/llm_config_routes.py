"""
@fileoverview LLM Config Dashboard Routes - Dashboard routes for LLM configuration management

@description
Dashboard routes for managing LLM provider and use case configuration.
Provides web interface for selecting providers and models per use case.

@module dashboard.routes.llm_config_routes

@exports
- llm_config: Blueprint - Flask blueprint for LLM config dashboard routes
"""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportGeneralTypeIssues=false, reportUnnecessaryIsInstance=false

from flask import Blueprint, render_template, request, jsonify, Response
from typing import Any, Dict, List, Optional
from pathlib import Path
import yaml
import tempfile
import os
from io import BytesIO

from src.core.llm import LLMConfigManager, UseCase, ProviderManager
from src.core.llm.test_case_loader import load_test_cases, load_test_case, list_available_test_cases
from src.core.llm.test_executor import LLMTestExecutor
from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.core.mongodb.llm_model_repository import (
    LLMModelRepository,
    LLMTestResultRepository,
    LLMUseCaseConfigRepository
)
from pymongo import DESCENDING
from src.core.models.llm_models import LLMModel, LLMTestResult
from src.core.llm.model_selector import LLMModelSelector

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

            # Dynamische Use-Case-Liste (aus Enum), damit neue Use-Cases ohne Template-Anpassung
            # automatisch in der UI erscheinen.
            all_use_cases: List[str] = [uc.value for uc in UseCase]

            # UI-Labels (Fallback: use_case string)
            use_case_labels: Dict[str, str] = {
                "transcription": "Transcription (Audio/Video)",
                "image2text": "Image2Text (Vision API)",
                "ocr_pdf": "OCR PDF",
                "chat_completion": "Chat Completion & Translation",
                "embedding": "Embedding",
                "transformer_xxl": "Transformer XXL (Large-File Summarization)",
            }

            # Konservative Defaults (nur wenn noch nicht konfiguriert)
            use_case_defaults: Dict[str, Dict[str, str]] = {
                "transcription": {"provider": "openai", "model": "whisper-1"},
                "image2text": {"provider": "openai", "model": "gpt-4o"},
                "ocr_pdf": {"provider": "mistral", "model": "pixtral-large-latest"},
                "chat_completion": {"provider": "openai", "model": "gpt-4.1-mini"},
                # XXL: Default wie spezifiziert
                "transformer_xxl": {"provider": "openrouter", "model": "google/gemini-2.5-flash"},
            }
            
            # Lade aktuelle Konfiguration für Anzeige
            app_config = Config()
            config_data = app_config.get_all()
            llm_config_data = config_data.get('llm_config', {})
            
            context = {
                'providers': providers_dict,
                'use_cases': use_cases_dict,
                'llm_config': llm_config_data,
                'all_use_cases': all_use_cases,
                'use_case_labels': use_case_labels,
                'use_case_defaults': use_case_defaults,
            }
            
            return render_template('llm_config.html', **context)
        except Exception as e:
            logger.error(f"Fehler beim Laden der LLM-Konfiguration: {str(e)}")
            # Zeige Seite auch bei Fehlern, aber mit Fehlermeldung
            return render_template('llm_config.html', 
                                 error=f"Fehler beim Laden der Konfiguration: {str(e)}",
                                 providers={},
                                 use_cases={},
                                 llm_config={},
                                 all_use_cases=[uc.value for uc in UseCase],
                                 use_case_labels={},
                                 use_case_defaults={})
    except Exception as e:
        logger.error(f"Fehler beim Laden der LLM-Konfigurationsseite: {str(e)}")
        return render_template(
            'llm_config.html',
            error=str(e),
            providers={},
            use_cases={},
            llm_config={},
            all_use_cases=[uc.value for uc in UseCase],
            use_case_labels={},
            use_case_defaults={},
        )


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


@llm_config.route('/llm-config/api/use-case-config', methods=['GET'])
def get_use_case_config_api() -> Any:
    """
    Gibt die aktuelle Konfiguration für einen Use-Case zurück.
    
    Query Parameters:
        use_case: Name des Use-Cases
        
    Returns:
        JSON: Provider und Modell für den Use-Case
    """
    try:
        use_case_str = request.args.get('use_case')
        
        if not use_case_str:
            return jsonify({
                "status": "error",
                "message": "use_case Parameter fehlt"
            }), 400
        
        try:
            use_case = UseCase(use_case_str)
        except ValueError:
            return jsonify({
                "status": "error",
                "message": f"Ungültiger Use-Case: {use_case_str}"
            }), 400
        
        config_manager = LLMConfigManager()
        provider = config_manager.get_provider_for_use_case(use_case)
        model = config_manager.get_model_for_use_case(use_case)
        
        if not provider:
            return jsonify({
                "status": "error",
                "message": f"Kein Provider für Use-Case '{use_case_str}' konfiguriert"
            }), 404
        
        return jsonify({
            "status": "success",
            "data": {
                "use_case": use_case_str,
                "provider": provider.get_provider_name(),
                "model": model
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Use-Case-Konfiguration: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/save', methods=['POST'])
def save_config_api() -> Any:
    """
    [DEPRECATED] Speichert die LLM-Konfiguration in config.yaml.
    
    WICHTIG: Diese Funktion ist veraltet! Das Frontend verwendet jetzt die MongoDB-API:
    PUT /llm-config/api/use-cases/<use_case>/current-model
    
    Diese Funktion wird nur noch für Kompatibilität/Import-Zwecke aufrechterhalten.
    
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
                        if model not in available_models:
                            test_results.append({
                                "use_case": use_case_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "warning",
                                "message": f"Modell '{model}' nicht in verfügbaren Modellen: {available_models}"
                            })
                            return jsonify({
                                "status": "warning",
                                "results": test_results
                            })
                        
                        # Teste mit echtem API-Call (nur für Chat-Completion)
                        if use_case == UseCase.CHAT_COMPLETION and hasattr(provider, 'chat_completion'):
                            try:
                                # Mache einen minimalen Test-Call
                                test_messages = [{"role": "user", "content": "Test"}]
                                _response, _llm_request = provider.chat_completion(
                                    messages=test_messages,
                                    model=model,
                                    temperature=0.1,
                                    max_tokens=10
                                )
                                test_results.append({
                                    "use_case": use_case_name,
                                    "provider": provider.get_provider_name(),
                                    "model": model,
                                    "status": "success",
                                    "message": f"Konfiguration gültig und API-Call erfolgreich: {provider.get_provider_name()} / {model}"
                                })
                            except Exception as api_error:
                                error_msg = str(api_error)
                                # Prüfe auf spezifische Fehler
                                if "invalid model" in error_msg.lower() or "model not found" in error_msg.lower():
                                    test_results.append({
                                        "use_case": use_case_name,
                                        "provider": provider.get_provider_name(),
                                        "model": model,
                                        "status": "error",
                                        "message": f"Modell '{model}' existiert nicht beim Provider {provider.get_provider_name()}. Fehler: {error_msg}"
                                    })
                                else:
                                    test_results.append({
                                        "use_case": use_case_name,
                                        "provider": provider.get_provider_name(),
                                        "model": model,
                                        "status": "error",
                                        "message": f"API-Call fehlgeschlagen: {error_msg}"
                                    })
                        else:
                            # Für andere Use-Cases nur Config-Validierung
                            test_results.append({
                                "use_case": use_case_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "success",
                                "message": f"Konfiguration gültig: {provider.get_provider_name()} / {model} (nur Config-Validierung, kein API-Call)"
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
                        if model not in available_models:
                            test_results.append({
                                "use_case": uc_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "warning",
                                "message": f"Modell '{model}' nicht in verfügbaren Modellen: {available_models}"
                            })
                            continue
                        
                        # Teste mit echtem API-Call (nur für Chat-Completion)
                        if use_case == UseCase.CHAT_COMPLETION and hasattr(provider, 'chat_completion'):
                            try:
                                # Mache einen minimalen Test-Call
                                test_messages = [{"role": "user", "content": "Test"}]
                                _response, _llm_request = provider.chat_completion(
                                    messages=test_messages,
                                    model=model,
                                    temperature=0.1,
                                    max_tokens=10
                                )
                                test_results.append({
                                    "use_case": uc_name,
                                    "provider": provider.get_provider_name(),
                                    "model": model,
                                    "status": "success",
                                    "message": f"Konfiguration gültig und API-Call erfolgreich: {provider.get_provider_name()} / {model}"
                                })
                            except Exception as api_error:
                                error_msg = str(api_error)
                                # Prüfe auf spezifische Fehler
                                if "invalid model" in error_msg.lower() or "model not found" in error_msg.lower():
                                    test_results.append({
                                        "use_case": uc_name,
                                        "provider": provider.get_provider_name(),
                                        "model": model,
                                        "status": "error",
                                        "message": f"Modell '{model}' existiert nicht beim Provider {provider.get_provider_name()}. Fehler: {error_msg}"
                                    })
                                else:
                                    test_results.append({
                                        "use_case": uc_name,
                                        "provider": provider.get_provider_name(),
                                        "model": model,
                                        "status": "error",
                                        "message": f"API-Call fehlgeschlagen: {error_msg}"
                                    })
                        else:
                            # Für andere Use-Cases nur Config-Validierung
                            test_results.append({
                                "use_case": uc_name,
                                "provider": provider.get_provider_name(),
                                "model": model,
                                "status": "success",
                                "message": f"Konfiguration gültig: {provider.get_provider_name()} / {model} (nur Config-Validierung, kein API-Call)"
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


@llm_config.route('/llm-config/api/test-cases/<use_case>', methods=['GET'])
def get_test_cases_api(use_case: str) -> Any:
    """
    Gibt alle verfügbaren Test-Cases für einen Use-Case zurück.
    
    Args:
        use_case: Name des Use-Cases
        
    Returns:
        JSON: Liste der verfügbaren Test-Cases
    """
    try:
        test_cases = load_test_cases(use_case)
        
        # Konvertiere zu Dictionary-Format
        test_cases_dict = {
            size: test_case.to_dict()
            for size, test_case in test_cases.items()
        }
        
        return jsonify({
            "status": "success",
            "data": {
                "use_case": use_case,
                "test_cases": test_cases_dict
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Laden der Test-Cases für {use_case}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Laden der Test-Cases: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/test-cases/execute', methods=['POST'])
def execute_test_case_api() -> Any:
    """
    Führt einen Test-Case aus.
    
    Request Body:
        use_case: Name des Use-Cases
        size: Größe des Tests ('small', 'medium', 'large')
        
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
        
        use_case = data.get('use_case')
        size = data.get('size')
        
        if not use_case:
            return jsonify({
                "status": "error",
                "message": "use_case Parameter fehlt"
            }), 400
        
        if not size:
            return jsonify({
                "status": "error",
                "message": "size Parameter fehlt"
            }), 400
        
        if size not in ['small', 'medium', 'large']:
            return jsonify({
                "status": "error",
                "message": f"Ungültige size: '{size}'. Muss 'small', 'medium' oder 'large' sein"
            }), 400
        
        # Lade Test-Case
        test_case = load_test_case(use_case, size)
        if not test_case:
            return jsonify({
                "status": "error",
                "message": f"Test-Case für {use_case}/{size} nicht gefunden"
            }), 404
        
        # Führe Test aus
        executor = LLMTestExecutor()
        result = executor.execute_test(test_case)
        
        return jsonify({
            "status": "success",
            "data": result
        })
    except Exception as e:
        logger.error(f"Fehler beim Ausführen des Test-Cases: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Ausführen des Tests: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/test-cases/batch-execute', methods=['POST'])
def batch_execute_test_cases_api() -> Any:
    """
    Führt Batch-Tests für mehrere Modelle aus.
    
    Request Body:
        use_case: Name des Use-Cases
        size: Größe des Tests ('small', 'medium', 'large')
        models: Liste von Modellnamen zum Testen
        provider: Name des Providers (optional, wird aus Config genommen wenn nicht angegeben)
        execution_mode: 'sequential' oder 'parallel' (default: 'sequential')
        
    Returns:
        JSON: Array von Testergebnissen (eines pro Modell)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        use_case = data.get('use_case')
        size = data.get('size')
        models = data.get('models', [])
        provider = data.get('provider')
        execution_mode = data.get('execution_mode', 'sequential')
        
        if not use_case:
            return jsonify({
                "status": "error",
                "message": "use_case Parameter fehlt"
            }), 400
        
        if not size:
            return jsonify({
                "status": "error",
                "message": "size Parameter fehlt"
            }), 400
        
        if size not in ['small', 'medium', 'large']:
            return jsonify({
                "status": "error",
                "message": f"Ungültige size: '{size}'. Muss 'small', 'medium' oder 'large' sein"
            }), 400
        
        if not models or not isinstance(models, list):
            return jsonify({
                "status": "error",
                "message": "models Parameter muss eine nicht-leere Liste sein"
            }), 400
        
        if execution_mode not in ['sequential', 'parallel']:
            return jsonify({
                "status": "error",
                "message": f"Ungültiger execution_mode: '{execution_mode}'. Muss 'sequential' oder 'parallel' sein"
            }), 400
        
        # Lade Test-Case
        test_case = load_test_case(use_case, size)
        if not test_case:
            return jsonify({
                "status": "error",
                "message": f"Test-Case für {use_case}/{size} nicht gefunden"
            }), 404
        
        # Bestimme Provider falls nicht angegeben
        config_manager = LLMConfigManager()
        if not provider:
            try:
                use_case_enum = UseCase(use_case)
                configured_provider = config_manager.get_provider_for_use_case(use_case_enum)
                if configured_provider:
                    provider = configured_provider.get_provider_name()
                else:
                    return jsonify({
                        "status": "error",
                        "message": f"Kein Provider für Use-Case '{use_case}' konfiguriert und kein Provider angegeben"
                    }), 400
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": f"Fehler beim Bestimmen des Providers: {str(e)}"
                }), 400
        
                # Führe Tests aus
        executor = LLMTestExecutor()
        results = []
        
        if execution_mode == 'sequential':
            # Sequenzielle Ausführung
            for i, model in enumerate(models):
                # Extrahiere Provider aus model_id falls vorhanden (Format: provider/model_name)
                model_provider = provider
                model_name = model
                if '/' in model:
                    parts = model.split('/', 1)
                    model_provider = parts[0]
                    model_name = parts[1]
                
                try:
                    result = executor.execute_test(
                        test_case=test_case,
                        model=model_name,
                        provider=model_provider
                    )
                    result['model'] = model_name
                    result['model_id'] = model  # Behalte vollständige model_id
                    result['provider'] = model_provider
                    result['index'] = i + 1
                    result['total'] = len(models)
                    results.append(result)
                    
                    # Speichere Test-Ergebnis in MongoDB (wird bereits im executor gemacht, aber sicherstellen)
                    # Der Executor speichert automatisch, aber wir können hier nochmal speichern falls nötig
                except Exception as e:
                    results.append({
                        "status": "error",
                        "model": model_name,
                        "model_id": model,
                        "provider": model_provider,
                        "index": i + 1,
                        "total": len(models),
                        "duration_ms": 0,
                        "tokens": 0,
                        "error": {
                            "code": "EXECUTION_ERROR",
                            "message": f"Fehler beim Testen von Modell '{model}': {str(e)}"
                        }
                    })
        else:
            # Parallele Ausführung
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def execute_single_test(model_id: str, index: int) -> Dict[str, Any]:
                """Führt einen einzelnen Test aus."""
                # Extrahiere Provider aus model_id falls vorhanden (Format: provider/model_name)
                model_provider = provider
                model_name = model_id
                if '/' in model_id:
                    parts = model_id.split('/', 1)
                    model_provider = parts[0]
                    model_name = parts[1]
                
                try:
                    result = executor.execute_test(
                        test_case=test_case,
                        model=model_name,
                        provider=model_provider
                    )
                    result['model'] = model_name
                    result['model_id'] = model_id  # Behalte vollständige model_id
                    result['provider'] = model_provider
                    result['index'] = index + 1
                    result['total'] = len(models)
                    return result
                except Exception as e:
                    return {
                        "status": "error",
                        "model": model_name,
                        "model_id": model_id,
                        "provider": model_provider,
                        "index": index + 1,
                        "total": len(models),
                        "duration_ms": 0,
                        "tokens": 0,
                        "error": {
                            "code": "EXECUTION_ERROR",
                            "message": f"Fehler beim Testen von Modell '{model_id}': {str(e)}"
                        }
                    }
            
            # Führe alle Tests parallel aus (max 5 gleichzeitig)
            max_workers = min(5, len(models))
            with ThreadPoolExecutor(max_workers=max_workers) as executor_pool:
                future_to_model = {
                    executor_pool.submit(execute_single_test, model, i): (model, i)
                    for i, model in enumerate(models)
                }
                
                for future in as_completed(future_to_model):
                    result = future.result()
                    results.append(result)
            
            # Sortiere Ergebnisse nach Index, um Reihenfolge beizubehalten.
            # Defensive Typisierung, da `results` dynamische JSON-Dicts enthält.
            def _sort_key(item: Any) -> int:
                if isinstance(item, dict):
                    try:
                        return int(item.get("index", 0))
                    except Exception:
                        return 0
                return 0

            results.sort(key=_sort_key)
        
        return jsonify({
            "status": "success",
            "data": {
                "use_case": use_case,
                "size": size,
                "provider": provider,
                "execution_mode": execution_mode,
                "results": results,
                "total_tests": len(models),
                "successful_tests": len([r for r in results if r.get('status') == 'success']),
                "failed_tests": len([r for r in results if r.get('status') == 'error'])
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Batch-Ausführen der Test-Cases: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Batch-Ausführen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/test-cases/available', methods=['GET'])
def get_available_test_cases_api() -> Any:
    """
    Gibt eine Übersicht aller verfügbaren Test-Cases zurück.
    
    Returns:
        JSON: Übersicht der verfügbaren Test-Cases
    """
    try:
        available = list_available_test_cases()
        
        return jsonify({
            "status": "success",
            "data": {
                "available_test_cases": available
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der verfügbaren Test-Cases: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models', methods=['GET'])
def get_models_api() -> Any:
    """
    Gibt alle Modelle zurück (mit optionalen Filtern).
    
    Query Parameters:
        provider: Optional, Filter nach Provider
        use_case: Optional, Filter nach Use-Case
        enabled: Optional, Filter nach Enabled-Status (true/false)
        
    Returns:
        JSON: Liste der Modelle
    """
    try:
        provider_filter = request.args.get('provider')
        use_case_filter = request.args.get('use_case')
        enabled_filter = request.args.get('enabled')
        
        model_repo = LLMModelRepository()
        
        # Starte mit allen Modellen
        models = model_repo.get_all_models(enabled_only=False)
        
        # Filtere nach Provider (falls angegeben)
        if provider_filter:
            models = [m for m in models if m.provider == provider_filter]
        
        # Filtere nach Use-Case (falls angegeben)
        if use_case_filter:
            models = [m for m in models if use_case_filter in m.use_cases]
        
        # Filtere nach enabled Status (falls angegeben)
        if enabled_filter:
            enabled_bool = enabled_filter.lower() == 'true'
            models = [m for m in models if m.enabled == enabled_bool]
        
        # Filtere nach Provider-Teil im Modellnamen (z.B. "openai" aus "openai/gpt-4")
        model_name_provider_filter = request.args.get('model_name_provider')
        if model_name_provider_filter:
            models = [m for m in models if model_name_provider_filter.lower() in m.model_name.lower()]
        
        # Gib immer vollständige Objekte zurück
        return jsonify({
            "status": "success",
            "data": [model.to_dict() for model in models]
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Modelle: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models/<path:model_id>', methods=['GET'])
def get_model_api(model_id: str) -> Any:
    """
    Gibt ein einzelnes Modell zurück.
    
    Args:
        model_id: Die Modell-ID (Format: provider/model_name)
        
    Returns:
        JSON: Modell-Daten
    """
    try:
        model_repo = LLMModelRepository()
        model = model_repo.get_model(model_id)
        
        if not model:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} nicht gefunden"
            }), 404
        
        return jsonify({
            "status": "success",
            "data": model.to_dict()
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Modells {model_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models', methods=['POST'])
def create_model_api() -> Any:
    """
    Erstellt ein neues Modell.
    
    Request Body:
        provider: Provider-Name
        model_name: Modell-Name
        use_cases: Liste der Use-Cases
        enabled: Ob aktiviert (default: true)
        description: Optional, Beschreibung
        metadata: Optional, Metadaten
        
    Returns:
        JSON: Erstelltes Modell
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        provider = data.get('provider')
        model_name = data.get('model_name')
        use_cases = data.get('use_cases', [])
        
        if not provider or not model_name:
            return jsonify({
                "status": "error",
                "message": "provider und model_name sind erforderlich"
            }), 400
        
        # Erstelle Modell-ID
        model_id = f"{provider}/{model_name}"
        
        model_repo = LLMModelRepository()
        
        # Prüfe ob bereits existiert
        existing = model_repo.get_model(model_id)
        if existing:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} existiert bereits"
            }), 409
        
        # Erstelle Modell
        model = LLMModel(
            model_id=model_id,
            provider=provider,
            model_name=model_name,
            use_cases=use_cases if isinstance(use_cases, list) else [],
            enabled=data.get('enabled', True),
            description=data.get('description'),
            metadata=data.get('metadata', {})
        )
        
        model_repo.create_model(model)
        
        return jsonify({
            "status": "success",
            "data": model.to_dict()
        }), 201
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Modells: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Erstellen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models/<path:model_id>', methods=['PUT'])
def update_model_api(model_id: str) -> Any:
    """
    Aktualisiert ein Modell.
    
    Args:
        model_id: Die Modell-ID
        
    Request Body:
        use_cases: Optional, Liste der Use-Cases
        enabled: Optional, Enabled-Status
        description: Optional, Beschreibung
        metadata: Optional, Metadaten
        
    Returns:
        JSON: Aktualisiertes Modell
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        model_repo = LLMModelRepository()
        
        # Prüfe ob Modell existiert
        existing = model_repo.get_model(model_id)
        if not existing:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} nicht gefunden"
            }), 404
        
        # Erstelle Updates-Dictionary (nur erlaubte Felder)
        updates: Dict[str, Any] = {}
        if 'use_cases' in data:
            updates['use_cases'] = data['use_cases']
        if 'enabled' in data:
            updates['enabled'] = data['enabled']
        if 'description' in data:
            updates['description'] = data.get('description')
        if 'metadata' in data:
            updates['metadata'] = data['metadata']
        
        if not updates:
            return jsonify({
                "status": "error",
                "message": "Keine gültigen Updates angegeben"
            }), 400
        
        # Aktualisiere Modell
        success = model_repo.update_model(model_id, updates)
        
        if success:
            updated_model = model_repo.get_model(model_id)
            return jsonify({
                "status": "success",
                "data": updated_model.to_dict() if updated_model else {}
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Fehler beim Aktualisieren"
            }), 500
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren des Modells {model_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Aktualisieren: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models/<path:model_id>', methods=['DELETE'])
def delete_model_api(model_id: str) -> Any:
    """
    Löscht ein Modell.
    
    Args:
        model_id: Die Modell-ID
        
    Returns:
        JSON: Erfolgsmeldung
    """
    try:
        model_repo = LLMModelRepository()
        
        # Prüfe ob Modell existiert
        existing = model_repo.get_model(model_id)
        if not existing:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} nicht gefunden"
            }), 404
        
        # Prüfe ob Modell in Use-Case-Konfigurationen verwendet wird
        use_case_config_repo = LLMUseCaseConfigRepository()
        all_configs = use_case_config_repo.get_all_use_case_configs()
        used_in = [uc for uc, mid in all_configs.items() if mid == model_id]
        
        if used_in:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} wird noch in folgenden Use-Cases verwendet: {', '.join(used_in)}"
            }), 409
        
        # Lösche Modell
        success = model_repo.delete_model(model_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Modell {model_id} gelöscht"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Fehler beim Löschen"
            }), 500
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Modells {model_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models/<path:model_id>/quality-scores', methods=['GET'])
def get_model_quality_scores_api(model_id: str) -> Any:
    """
    Gibt die Quality Scores für ein Modell für alle Test-Sizes zurück.
    
    Args:
        model_id: Die Modell-ID
        
    Returns:
        JSON: Quality Scores für small, medium, large
    """
    try:
        test_result_repo = LLMTestResultRepository()
        
        # Lade Test-Ergebnisse für alle Test-Sizes
        quality_scores: Dict[str, Optional[float]] = {
            "small": None,
            "medium": None,
            "large": None
        }
        
        for test_size in ["small", "medium", "large"]:
            # Lade alle erfolgreichen Test-Ergebnisse für diese Test-Size
            results = test_result_repo.test_results.find({
                "model_id": model_id,
                "test_size": test_size,
                "status": "success",
                "quality_score": {"$exists": True, "$ne": None}
            }).sort("tested_at", DESCENDING)
            
            # Berechne Durchschnitt der Quality Scores
            scores = [r.get("quality_score") for r in results if r.get("quality_score") is not None]
            if scores:
                quality_scores[test_size] = sum(scores) / len(scores)
        
        return jsonify({
            "status": "success",
            "data": quality_scores
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Quality Scores für {model_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/models/<path:model_id>/test-results', methods=['GET'])
def get_model_test_results_api(model_id: str) -> Any:
    """
    Gibt Test-Ergebnisse für ein Modell zurück.
    
    Args:
        model_id: Die Modell-ID
        
    Query Parameters:
        use_case: Optional, Filter nach Use-Case
        test_size: Optional, Filter nach Test-Größe
        
    Returns:
        JSON: Liste der Test-Ergebnisse
    """
    try:
        use_case_filter = request.args.get('use_case')
        test_size_filter = request.args.get('test_size')
        
        test_result_repo = LLMTestResultRepository()
        
        if use_case_filter and test_size_filter:
            # Spezifisches Ergebnis
            result = test_result_repo.get_test_result(model_id, use_case_filter, test_size_filter)
            results = [result] if result else []
        elif use_case_filter:
            # Alle Ergebnisse für Use-Case
            all_results = test_result_repo.get_test_results_by_model(model_id)
            results = [r for r in all_results if r.use_case == use_case_filter]
        else:
            # Alle Ergebnisse für Modell
            results = test_result_repo.get_test_results_by_model(model_id)
        
        return jsonify({
            "status": "success",
            "data": [result.to_dict() for result in results]
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Test-Ergebnisse für {model_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/use-cases/<use_case>/latest-test-results', methods=['GET'])
def get_latest_test_results_for_use_case_api(use_case: str) -> Any:
    """
    Gibt die letzten Test-Ergebnisse für einen Use-Case zurück, gruppiert nach Test-Size.
    
    Args:
        use_case: Der Use-Case
        
    Query Parameters:
        test_size: Optional, Filter nach Test-Größe
        
    Returns:
        JSON: Dictionary mit Test-Size als Key und Liste der letzten Ergebnisse als Value
    """
    try:
        test_size_filter = request.args.get('test_size')
        test_result_repo = LLMTestResultRepository()
        
        # Lade alle Test-Ergebnisse für diesen Use-Case
        all_results = test_result_repo.get_test_results_by_use_case(use_case)
        
        # Filtere nach test_size falls angegeben
        if test_size_filter:
            all_results = [r for r in all_results if r.test_size == test_size_filter]
        
        # Gruppiere nach test_size und behalte nur die neuesten Ergebnisse pro Modell
        results_by_size: Dict[str, Dict[str, LLMTestResult]] = {}
        
        for result in all_results:
            size = result.test_size
            model_id = result.model_id
            
            if size not in results_by_size:
                results_by_size[size] = {}
            
            # Behalte nur das neueste Ergebnis pro Modell
            if model_id not in results_by_size[size]:
                results_by_size[size][model_id] = result
            else:
                # Vergleiche tested_at und behalte das neueste
                existing = results_by_size[size][model_id]
                if result.tested_at > existing.tested_at:
                    results_by_size[size][model_id] = result
        
        # Konvertiere zu Dictionary mit Listen
        response_data: Dict[str, List[Dict[str, Any]]] = {}
        for size, model_results in results_by_size.items():
            # Konvertiere zu Dictionary-Format für Frontend
            response_data[size] = []
            for result in model_results.values():
                # Konvertiere LLMTestResult zu Dictionary-Format wie bei batch_execute
                result_dict = {
                    "model": result.model_id.split('/')[-1] if '/' in result.model_id else result.model_id,
                    "model_id": result.model_id,
                    "provider": result.model_id.split('/')[0] if '/' in result.model_id else 'unknown',
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "quality_score": result.quality_score,
                    "error_message": result.error_message,
                    "error_code": result.error_code,
                    "tested_at": result.tested_at.isoformat() if result.tested_at else None,
                    "llm_info": result.test_result_data.get("llm_info", {}),
                    "response": {
                        "data": {
                            "data": {
                                "structured_data": result.test_result_data.get("response", {}).get("data", {}).get("data", {}).get("structured_data")
                            }
                        }
                    }
                }
                response_data[size].append(result_dict)
        
        return jsonify({
            "status": "success",
            "data": response_data
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der letzten Test-Ergebnisse für {use_case}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/use-cases/<use_case>/current-model', methods=['GET'])
def get_current_model_for_use_case_api(use_case: str) -> Any:
    """
    Gibt das aktuell konfigurierte Modell für einen Use-Case zurück.
    
    Args:
        use_case: Der Use-Case
        
    Returns:
        JSON: Modell-ID
    """
    try:
        use_case_config_repo = LLMUseCaseConfigRepository()
        model_id = use_case_config_repo.get_current_model(use_case)
        
        if not model_id:
            return jsonify({
                "status": "error",
                "message": f"Kein Modell für Use-Case {use_case} konfiguriert"
            }), 404
        
        # Lade Modell-Details
        model_repo = LLMModelRepository()
        model = model_repo.get_model(model_id)
        
        return jsonify({
            "status": "success",
            "data": {
                "model_id": model_id,
                "model": model.to_dict() if model else None
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des aktuellen Modells für {use_case}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/use-cases/<use_case>/current-model', methods=['PUT'])
def set_current_model_for_use_case_api(use_case: str) -> Any:
    """
    Setzt das aktuelle Modell für einen Use-Case.
    
    Args:
        use_case: Der Use-Case
        
    Request Body:
        model_id: Die Modell-ID
        
    Returns:
        JSON: Erfolgsmeldung
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "Keine Daten im Request-Body"
            }), 400
        
        model_id = data.get('model_id')
        if not model_id:
            return jsonify({
                "status": "error",
                "message": "model_id ist erforderlich"
            }), 400
        
        # Validiere dass Modell existiert
        model_repo = LLMModelRepository()
        model = model_repo.get_model(model_id)
        if not model:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} existiert nicht in MongoDB. Bitte erstellen Sie das Modell zuerst im Tab 'Available LLMs'.",
                "details": {
                    "model_id": model_id,
                    "use_case": use_case,
                    "hint": "Gehen Sie zu 'Available LLMs' und erstellen Sie das Modell mit dem Use-Case 'chat_completion'"
                }
            }), 404
        
        # Validiere dass Modell den Use-Case unterstützt
        if use_case not in model.use_cases:
            return jsonify({
                "status": "error",
                "message": f"Modell {model_id} unterstützt Use-Case {use_case} nicht. Unterstützte Use-Cases: {', '.join(model.use_cases)}",
                "details": {
                    "model_id": model_id,
                    "use_case": use_case,
                    "supported_use_cases": model.use_cases,
                    "hint": f"Bitte bearbeiten Sie das Modell im Tab 'Available LLMs' und fügen Sie '{use_case}' zu den unterstützten Use-Cases hinzu"
                }
            }), 400
        
        # Setze aktuelles Modell
        use_case_config_repo = LLMUseCaseConfigRepository()
        success = use_case_config_repo.set_current_model(use_case, model_id)
        
        if success:
            # Lade Config neu
            config_manager = LLMConfigManager()
            config_manager.reload_config()
            
            return jsonify({
                "status": "success",
                "message": f"Aktuelles Modell für {use_case} auf {model_id} gesetzt"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Fehler beim Setzen des Modells"
            }), 500
    except Exception as e:
        logger.error(f"Fehler beim Setzen des aktuellen Modells für {use_case}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Setzen: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/use-cases/<use_case>/best-model', methods=['GET'])
def get_best_model_for_use_case_api(use_case: str) -> Any:
    """
    Gibt das beste Modell für einen Use-Case basierend auf Test-Ergebnissen zurück.
    
    Args:
        use_case: Der Use-Case
        
    Query Parameters:
        test_size: Test-Größe (default: "medium")
        criteria: Kriterium ("duration", "tokens", "reliability", default: "duration")
        
    Returns:
        JSON: Modell-ID des besten Modells
    """
    try:
        test_size = request.args.get('test_size', 'medium')
        criteria = request.args.get('criteria', 'duration')
        
        selector = LLMModelSelector()
        best_model_id = selector.get_best_model_for_use_case(use_case, test_size, criteria)
        
        if not best_model_id:
            return jsonify({
                "status": "error",
                "message": f"Kein Modell für Use-Case {use_case} gefunden"
            }), 404
        
        # Lade Modell-Details
        model_repo = LLMModelRepository()
        model = model_repo.get_model(best_model_id)
        
        return jsonify({
            "status": "success",
            "data": {
                "model_id": best_model_id,
                "model": model.to_dict() if model else None,
                "test_size": test_size,
                "criteria": criteria
            }
        })
    except Exception as e:
        logger.error(f"Fehler beim Finden des besten Modells für {use_case}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Finden: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/import-config', methods=['POST'])
def import_config_api() -> Any:
    """
    Importiert LLM-Konfiguration aus einer config.yaml Datei nach MongoDB.
    
    Request:
        config_file: Uploaded YAML file
        
    Returns:
        JSON: Import-Ergebnis mit Anzahl importierter Modelle und Konfigurationen
    """
    try:
        if 'config_file' not in request.files:
            return jsonify({
                "status": "error",
                "message": "Keine Datei hochgeladen"
            }), 400
        
        file = request.files['config_file']
        
        if not file or file.filename == '':
            return jsonify({
                "status": "error",
                "message": "Keine Datei ausgewählt"
            }), 400
        
        filename = file.filename or ''
        if not (filename.endswith('.yaml') or filename.endswith('.yml')):
            return jsonify({
                "status": "error",
                "message": "Nur YAML-Dateien werden unterstützt"
            }), 400
        
        # Speichere temporäre Datei
        with tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.yaml') as tmp_file:
            file.save(tmp_file.name)
            tmp_path = tmp_file.name
        
        try:
            # Lade YAML-Datei
            import yaml
            with open(tmp_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if not config_data:
                return jsonify({
                    "status": "error",
                    "message": "YAML-Datei ist leer oder ungültig"
                }), 400
            
            # Migriere Modelle
            models_count = 0
            configs_count = 0
            
            llm_providers_config = config_data.get('llm_providers', {})
            model_repo = LLMModelRepository()
            
            # Durchlaufe alle Provider
            for provider_name, provider_data in llm_providers_config.items():
                if not isinstance(provider_data, dict):
                    continue
                
                if not provider_data.get('enabled', True):
                    continue
                
                available_models = provider_data.get('available_models', {})
                
                # Durchlaufe alle Use-Cases für diesen Provider
                for use_case, models_list in available_models.items():
                    if not isinstance(models_list, list):
                        continue
                    
                    # Erstelle Modell für jeden Eintrag
                    for model_name in models_list:
                        if not isinstance(model_name, str) or not model_name.strip():
                            continue
                        
                        model_id = f"{provider_name}/{model_name}"
                        
                        # Prüfe ob Modell bereits existiert
                        existing_model = model_repo.get_model(model_id)
                        
                        if existing_model:
                            # Aktualisiere Use-Cases falls nötig
                            if use_case not in existing_model.use_cases:
                                updated_use_cases = list(existing_model.use_cases) + [use_case]
                                model_repo.update_model(model_id, {"use_cases": updated_use_cases})
                        else:
                            # Erstelle neues Modell
                            try:
                                from src.core.models.llm_models import LLMModel
                                model = LLMModel(
                                    model_id=model_id,
                                    provider=provider_name,
                                    model_name=model_name,
                                    use_cases=[use_case],
                                    enabled=True
                                )
                                model_repo.create_model(model)
                                models_count += 1
                            except ValueError as e:
                                logger.warning(f"Fehler beim Erstellen des Modells {model_id}: {str(e)}")
            
            # Migriere Use-Case-Konfigurationen
            llm_config_data = config_data.get('llm_config', {})
            use_cases_config = llm_config_data.get('use_cases', {})
            config_repo = LLMUseCaseConfigRepository()
            
            for use_case_name, use_case_data in use_cases_config.items():
                if not isinstance(use_case_data, dict):
                    continue
                
                provider = use_case_data.get('provider')
                model = use_case_data.get('model')
                
                if not provider or not model:
                    continue
                
                model_id = f"{provider}/{model}"
                
                # Prüfe ob Modell existiert
                existing_model = model_repo.get_model(model_id)
                if not existing_model:
                    logger.warning(
                        f"Modell {model_id} für Use-Case {use_case_name} existiert nicht in MongoDB"
                    )
                    continue
                
                # Setze aktuelles Modell
                if config_repo.set_current_model(use_case_name, model_id):
                    configs_count += 1
            
            # Lade Config neu
            config_manager = LLMConfigManager()
            config_manager.reload_config()
            
            return jsonify({
                "status": "success",
                "data": {
                    "models_count": models_count,
                    "configs_count": configs_count
                },
                "message": f"Import erfolgreich: {models_count} Modelle, {configs_count} Konfigurationen"
            })
            
        finally:
            # Lösche temporäre Datei
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
                
    except Exception as e:
        # Prüfe ob es ein YAML-Fehler ist
        if 'yaml' in str(type(e).__module__).lower() or 'YAMLError' in str(type(e)):
            return jsonify({
                "status": "error",
                "message": f"Fehler beim Parsen der YAML-Datei: {str(e)}"
            }), 400
        
        logger.error(f"Fehler beim Importieren der Config: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Importieren: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/export-config', methods=['GET'])
def export_config_api() -> Any:
    """
    Exportiert LLM-Konfiguration aus MongoDB im config.yaml Format.
    
    Returns:
        YAML file: Exportierte Konfiguration
    """
    try:
        model_repo = LLMModelRepository()
        use_case_config_repo = LLMUseCaseConfigRepository()
        
        # Lade alle Modelle
        all_models = model_repo.get_all_models()
        
        # Lade alle Use-Case-Konfigurationen
        all_configs = use_case_config_repo.get_all_use_case_configs()
        
        # Lade Provider-Konfigurationen aus config.yaml (für API-Keys etc.)
        config = Config()
        config_data = config.get_all()
        llm_providers_config = config_data.get('llm_providers', {})
        
        # Erstelle Export-Struktur
        export_data = {
            'llm_providers': {},
            'llm_config': {
                'use_cases': {}
            }
        }
        
        # Gruppiere Modelle nach Provider
        models_by_provider: Dict[str, Dict[str, List[str]]] = {}
        
        for model in all_models:
            if model.provider not in models_by_provider:
                models_by_provider[model.provider] = {}
            
            for use_case in model.use_cases:
                if use_case not in models_by_provider[model.provider]:
                    models_by_provider[model.provider][use_case] = []
                
                if model.model_name not in models_by_provider[model.provider][use_case]:
                    models_by_provider[model.provider][use_case].append(model.model_name)
        
        # Erstelle llm_providers Struktur
        for provider_name, use_cases_dict in models_by_provider.items():
            # Lade Provider-Konfiguration aus config.yaml
            provider_config = llm_providers_config.get(provider_name, {})
            
            export_data['llm_providers'][provider_name] = {
                'api_key': provider_config.get('api_key', '${' + provider_name.upper() + '_API_KEY}'),
                'enabled': provider_config.get('enabled', True),
                'available_models': use_cases_dict
            }
            
            # Füge base_url hinzu falls vorhanden
            if 'base_url' in provider_config:
                export_data['llm_providers'][provider_name]['base_url'] = provider_config['base_url']
            
            # Füge additional_config hinzu falls vorhanden
            if 'additional_config' in provider_config:
                export_data['llm_providers'][provider_name]['additional_config'] = provider_config['additional_config']
        
        # Erstelle llm_config.use_cases Struktur
        for use_case_name, model_id in all_configs.items():
            # Extrahiere Provider und Modell-Name aus model_id
            if '/' in model_id:
                provider, model_name = model_id.split('/', 1)
                
                export_data['llm_config']['use_cases'][use_case_name] = {
                    'provider': provider,
                    'model': model_name
                }
                
                # Füge dimensions hinzu für embedding
                if use_case_name == 'embedding':
                    embedding_config = config_data.get('llm_config', {}).get('use_cases', {}).get('embedding', {})
                    if 'dimensions' in embedding_config:
                        export_data['llm_config']['use_cases'][use_case_name]['dimensions'] = embedding_config['dimensions']
        
        # Konvertiere zu YAML
        yaml_output = yaml.dump(export_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        # Erstelle Response
        response_buffer = BytesIO()
        response_buffer.write(yaml_output.encode('utf-8'))
        response_buffer.seek(0)
        
        return Response(
            response_buffer.read(),
            mimetype='application/x-yaml',
            headers={
                'Content-Disposition': 'attachment; filename=llm_config_export.yaml'
            }
        )
        
    except Exception as e:
        logger.error(f"Fehler beim Exportieren der Config: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Exportieren: {str(e)}"
        }), 500


@llm_config.route('/llm-config/api/openrouter/models', methods=['GET'])
def get_openrouter_models_from_api() -> Any:
    """
    Ruft die aktuell verfügbaren Modelle direkt von der OpenRouter API ab.
    Dies hilft bei der Diagnose, ob ein Modell noch verfügbar ist.
    
    Returns:
        JSON: Liste der verfügbaren Modelle von OpenRouter
    """
    try:
        config_manager = LLMConfigManager()
        provider_config = config_manager.get_provider_config('openrouter')
        
        if not provider_config or not provider_config.enabled:
            return jsonify({
                "status": "error",
                "message": "OpenRouter Provider nicht konfiguriert oder deaktiviert"
            }), 404
        
        # Erstelle Provider-Instanz
        provider_manager = ProviderManager()
        provider_kwargs = provider_config.additional_config.copy()
        if provider_config.available_models:
            provider_kwargs['available_models'] = provider_config.available_models
        
        provider = provider_manager.get_provider(
            provider_name='openrouter',
            api_key=provider_config.api_key,
            base_url=provider_config.base_url,
            **provider_kwargs
        )
        
        # Rufe Modelle von API ab (nur wenn der Provider diese Methode anbietet).
        # Typisch: OpenRouterProvider besitzt `fetch_models_from_api`.
        fetch_fn = getattr(provider, "fetch_models_from_api", None)
        if callable(fetch_fn):
            models_any = fetch_fn()
            if not isinstance(models_any, list):
                return jsonify({
                    "status": "error",
                    "message": "Unerwartetes Format der OpenRouter-Model-API (erwartet: Liste)"
                }), 500

            # Filtere auf Dicts, damit wir stabil `.get(...)` verwenden können.
            models: List[Dict[str, Any]] = [m for m in models_any if isinstance(m, dict)]

            if models:
                # Filtere nach Mistral-Modellen für bessere Übersicht
                mistral_models: List[Dict[str, Any]] = [
                    m for m in models
                    if 'id' in m and 'mistral' in str(m.get('id', '')).lower()
                ]
                
                return jsonify({
                    "status": "success",
                    "data": {
                        "all_models_count": len(models),
                        "mistral_models": [
                            {
                                "id": m.get('id'),
                                "name": m.get('name'),
                                "context_length": m.get('context_length'),
                                "pricing": m.get('pricing', {})
                            }
                            for m in mistral_models[:20]  # Zeige max. 20 Mistral-Modelle
                        ],
                        "all_model_ids": (
                            [m.get('id') for m in models[:50]]
                            if len(models) <= 50
                            else [m.get('id') for m in models[:50]] + [f"... und {len(models) - 50} weitere"]
                        )
                    }
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "Keine Modelle von OpenRouter API erhalten"
                }), 500
        else:
            return jsonify({
                "status": "error",
                "message": "Provider unterstützt keine API-Modellabfrage"
            }), 400
            
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der OpenRouter-Modelle: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen: {str(e)}"
        }), 500


