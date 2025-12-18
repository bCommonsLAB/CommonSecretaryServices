"""
@fileoverview LLM Test Executor - Executes LLM test cases

@description
Executes LLM test cases by making HTTP requests to the configured endpoints.
Uses the currently configured provider/model for the use case.

@module core.llm.test_executor

@exports
- LLMTestExecutor: Class - Test execution service
"""

import time
import json
from typing import Dict, Any, Optional, List

import requests

from ..models.llm_test import LLMTestCase
from ..models.llm_models import LLMTestResult
from .config_manager import LLMConfigManager
from .use_cases import UseCase
from .quality_calculator import QualityCalculator
from ..config import Config
import logging

logger = logging.getLogger(__name__)


class LLMTestExecutor:
    """
    Führt LLM-Test-Cases aus.
    
    Macht HTTP-Requests an die konfigurierten Endpoints und validiert
    die Ergebnisse basierend auf den Test-Case-Definitionen.
    """
    
    def __init__(self) -> None:
        """Initialisiert den Test-Executor."""
        self.config = Config()
        self.base_url = self.config.get('server', {}).get('api_base_url', 'http://localhost:5001')
        self.llm_config_manager = LLMConfigManager()
    
    def execute_test(
        self,
        test_case: LLMTestCase,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Führt einen Test-Case aus.
        
        Args:
            test_case: Der auszuführende Test-Case
            model: Optional, überschreibt das konfigurierte Modell für diesen Test
            provider: Optional, überschreibt den konfigurierten Provider für diesen Test
            timeout: Timeout für den Request in Sekunden (default: 300)
            
        Returns:
            Dict mit:
            - status: 'success' oder 'error'
            - test_case: Test-Case-Informationen
            - request: Request-Details
            - response: Response-Daten
            - duration_ms: Dauer in Millisekunden
            - llm_info: LLM-Nutzungsinformationen (falls verfügbar)
            - validation: Validierungsergebnisse
            - error: Fehlerinformationen (falls vorhanden)
        """
        start_time = time.time()
        
        try:
            # Prüfe ob Provider für Use-Case konfiguriert ist
            try:
                use_case_enum = UseCase(test_case.use_case)
                
                # Wenn ein expliziter Provider übergeben wurde, verwende diesen direkt
                # (Modell kommt aus MongoDB)
                if provider:
                    test_provider = provider
                    test_model = model if model else None
                    # Überspringe Validierung für MongoDB-Modelle
                else:
                    # Verwende konfigurierten Provider aus Config
                    configured_provider = self.llm_config_manager.get_provider_for_use_case(use_case_enum)
                    configured_model = self.llm_config_manager.get_model_for_use_case(use_case_enum)
                    
                    test_provider = configured_provider.get_provider_name() if configured_provider else None
                    test_model = model if model else configured_model
                    
                    # Validiere, dass überschriebenes Modell für Provider verfügbar ist
                    # Nur wenn Modell aus Config kommt (kein expliziter Provider)
                    if model and configured_provider:
                        try:
                            available_models = configured_provider.get_available_models(use_case_enum)
                            if model not in available_models:
                                return {
                                    "status": "error",
                                    "test_case": test_case.to_dict(),
                                    "error": {
                                        "code": "MODEL_NOT_AVAILABLE",
                                        "message": f"Modell '{model}' ist nicht für Provider '{test_provider}' verfügbar. Verfügbare Modelle: {available_models}"
                                    },
                                    "duration_ms": int((time.time() - start_time) * 1000)
                                }
                        except Exception:
                            # Wenn get_available_models fehlschlägt, ignorieren wir die Validierung
                            pass
                
            except Exception as e:
                # Wenn kein expliziter Provider übergeben wurde und Config-Fehler auftritt
                if not provider:
                    return {
                        "status": "error",
                        "test_case": test_case.to_dict(),
                        "error": {
                            "code": "PROVIDER_NOT_CONFIGURED",
                            "message": f"Provider für Use-Case '{test_case.use_case}' nicht konfiguriert: {str(e)}"
                        },
                        "duration_ms": int((time.time() - start_time) * 1000)
                    }
                # Wenn expliziter Provider übergeben wurde, verwende diesen trotzdem
                test_provider = provider
                test_model = model if model else None
            
            # Baue Request-URL
            url = f"{self.base_url}{test_case.endpoint}"
            
            # Bereite Request-Parameter vor (mit Modell-Überschreibung falls angegeben)
            request_params = test_case.parameters.copy()
            
            # Füge Modell und Provider als Request-Parameter hinzu, falls überschrieben
            # Dies ermöglicht es dem Backend, das Modell zu überschreiben
            if model:
                request_params['_test_model'] = model
            if provider:
                request_params['_test_provider'] = provider
            
            # Bereite Request vor
            headers: Dict[str, str] = {
                'Content-Type': 'application/json'
            }
            
            # Führe Request aus
            if test_case.method.upper() == 'POST':
                response = requests.post(
                    url,
                    json=request_params,
                    headers=headers,
                    timeout=timeout
                )
            elif test_case.method.upper() == 'GET':
                response = requests.get(
                    url,
                    params=request_params,
                    headers=headers,
                    timeout=timeout
                )
            else:
                return {
                    "status": "error",
                    "test_case": test_case.to_dict(),
                    "error": {
                        "code": "UNSUPPORTED_METHOD",
                        "message": f"HTTP-Methode '{test_case.method}' wird nicht unterstützt"
                    },
                    "duration_ms": int((time.time() - start_time) * 1000)
                }
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Parse Response
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = {"raw_response": response.text}
            
            # Extrahiere LLM-Info aus Response
            llm_info: Optional[Dict[str, Any]] = None
            if isinstance(response_data, dict):
                process_info = response_data.get('process', {})
                if isinstance(process_info, dict):
                    llm_info = process_info.get('llm_info')
            
            # Validiere Response
            validation_results = self._validate_response(
                test_case,
                response_data,
                response.status_code
            )
            
            # Bestimme Status
            status = "success" if response.status_code == 200 and validation_results.get("valid", False) else "error"
            
            # Berechne Quality Score wenn Test erfolgreich und structured_data vorhanden
            quality_score: Optional[float] = None
            input_embedding: Optional[List[float]] = None
            output_embedding: Optional[List[float]] = None
            
            if status == "success" and test_case.validate_json:
                try:
                    structured_data = self._get_nested_field(response_data, "data.structured_data")
                    if structured_data and isinstance(structured_data, dict):
                        quality_calculator = QualityCalculator()
                        quality_result = quality_calculator.calculate_quality_score(
                            test_case,
                            structured_data
                        )
                        if quality_result:
                            quality_score, input_embedding, output_embedding = quality_result
                except Exception as e:
                    # Fehler bei Quality-Berechnung sollte den Test nicht beeinflussen
                    logger.warning(f"Fehler bei der Quality-Berechnung: {str(e)}")
            
            result = {
                "status": status,
                "test_case": test_case.to_dict(),
                "request": {
                    "url": url,
                    "method": test_case.method,
                    "parameters": request_params
                },
                "response": {
                    "status_code": response.status_code,
                    "data": response_data
                },
                "duration_ms": duration_ms,
                "llm_info": llm_info,
                "validation": validation_results,
                "provider": test_provider,
                "model": test_model,
                "quality_score": quality_score,
                "input_embedding": input_embedding,
                "output_embedding": output_embedding
            }
            
            # Speichere Test-Ergebnis in MongoDB
            try:
                self._save_test_result_to_mongodb(
                    model_id=f"{test_provider}/{test_model}" if test_provider and test_model else None,
                    use_case=test_case.use_case,
                    test_size=test_case.size,
                    result=result
                )
            except Exception as e:
                # Fehler beim Speichern sollte den Test nicht beeinflussen
                logger.warning(f"Fehler beim Speichern des Test-Ergebnisses in MongoDB: {str(e)}")
            
            return result
            
        except requests.exceptions.Timeout:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "error",
                "test_case": test_case.to_dict(),
                "error": {
                    "code": "TIMEOUT",
                    "message": f"Request hat das Timeout von {timeout} Sekunden überschritten"
                },
                "duration_ms": duration_ms
            }
        except requests.exceptions.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "error",
                "test_case": test_case.to_dict(),
                "error": {
                    "code": "REQUEST_ERROR",
                    "message": f"Fehler beim Request: {str(e)}"
                },
                "duration_ms": duration_ms
            }
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "error",
                "test_case": test_case.to_dict(),
                "error": {
                    "code": "EXECUTION_ERROR",
                    "message": f"Unerwarteter Fehler: {str(e)}"
                },
                "duration_ms": duration_ms
            }
    
    def _validate_response(
        self,
        test_case: LLMTestCase,
        response_data: Dict[str, Any],
        status_code: int
    ) -> Dict[str, Any]:
        """
        Validiert die Response basierend auf den Test-Case-Anforderungen.
        
        Args:
            test_case: Der Test-Case
            response_data: Die Response-Daten
            status_code: HTTP-Status-Code
            
        Returns:
            Dict mit Validierungsergebnissen
        """
        results: Dict[str, Any] = {
            "valid": True,
            "checks": []
        }
        
        # Prüfe Status-Code
        if status_code != 200:
            results["valid"] = False
            results["checks"].append({
                "check": "status_code",
                "status": "error",
                "message": f"Erwartet Status 200, erhalten {status_code}"
            })
        else:
            results["checks"].append({
                "check": "status_code",
                "status": "success",
                "message": f"Status-Code: {status_code}"
            })
        
        # Prüfe erwartete Felder
        for field_path in test_case.expected_fields:
            field_value = self._get_nested_field(response_data, field_path)
            if field_value is None:
                results["valid"] = False
                results["checks"].append({
                    "check": f"field_exists:{field_path}",
                    "status": "error",
                    "message": f"Erwartetes Feld '{field_path}' nicht gefunden"
                })
            else:
                results["checks"].append({
                    "check": f"field_exists:{field_path}",
                    "status": "success",
                    "message": f"Feld '{field_path}' gefunden"
                })
        
        # JSON-Validierung für structured_data (falls aktiviert)
        if test_case.validate_json:
            structured_data = self._get_nested_field(response_data, "data.structured_data")
            if structured_data is None:
                results["valid"] = False
                results["checks"].append({
                    "check": "json_validation",
                    "status": "error",
                    "message": "structured_data Feld nicht gefunden"
                })
            else:
                # Prüfe ob es ein gültiges JSON-Objekt ist
                if isinstance(structured_data, dict):
                    # Versuche zu serialisieren um sicherzustellen, dass es gültiges JSON ist
                    try:
                        json.dumps(structured_data)
                        results["checks"].append({
                            "check": "json_validation",
                            "status": "success",
                            "message": "structured_data ist gültiges JSON"
                        })
                    except (TypeError, ValueError) as e:
                        results["valid"] = False
                        results["checks"].append({
                            "check": "json_validation",
                            "status": "error",
                            "message": f"structured_data ist kein gültiges JSON: {str(e)}"
                        })
                else:
                    results["valid"] = False
                    results["checks"].append({
                        "check": "json_validation",
                        "status": "error",
                        "message": f"structured_data ist kein Dictionary, sondern {type(structured_data).__name__}"
                    })
        
        return results
    
    def _get_nested_field(self, data: Dict[str, Any], field_path: str) -> Any:
        """
        Holt ein verschachteltes Feld aus einem Dictionary.
        
        Args:
            data: Das Dictionary
            field_path: Pfad zum Feld (z.B. 'data.structured_data')
            
        Returns:
            Der Feldwert oder None wenn nicht gefunden
        """
        parts = field_path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    def _save_test_result_to_mongodb(
        self,
        model_id: Optional[str],
        use_case: str,
        test_size: str,
        result: Dict[str, Any]
    ) -> None:
        """
        Speichert ein Test-Ergebnis in MongoDB.
        
        Args:
            model_id: Die Modell-ID (Format: provider/model_name)
            use_case: Der Use-Case
            test_size: Die Test-Größe
            result: Das Test-Result-Dictionary
        """
        if not model_id:
            logger.debug("Keine model_id verfügbar, überspringe MongoDB-Speicherung")
            return
        
        try:
            from ..mongodb.llm_model_repository import LLMTestResultRepository
            
            test_result_repo = LLMTestResultRepository()
            
            # Extrahiere Daten aus Result
            status = result.get("status", "error")
            duration_ms = result.get("duration_ms", 0)
            llm_info = result.get("llm_info", {})
            tokens = llm_info.get("total_tokens") if isinstance(llm_info, dict) else None
            
            validation = result.get("validation", {})
            validation_status = "success" if validation.get("valid", False) else "error"
            
            error_info = result.get("error", {})
            error_message = None
            error_code = None
            if isinstance(error_info, dict):
                error_message = error_info.get("message")
                error_code = error_info.get("code")
            
            # Extrahiere Quality-Daten
            quality_score = result.get("quality_score")
            input_embedding = result.get("input_embedding")
            output_embedding = result.get("output_embedding")
            
            # Bei fehlgeschlagenen Tests: Setze Quality-Werte auf None
            if status == "error":
                quality_score = None
                input_embedding = None
                output_embedding = None
            
            # Erstelle LLMTestResult
            test_result = LLMTestResult(
                model_id=model_id,
                use_case=use_case,
                test_size=test_size,
                status=status,
                duration_ms=duration_ms,
                tokens=tokens,
                error_message=error_message,
                error_code=error_code,
                validation_status=validation_status,
                test_result_data=result,
                quality_score=quality_score,
                input_embedding=input_embedding,
                output_embedding=output_embedding
            )
            
            # Speichere in MongoDB
            test_result_repo.save_test_result(test_result)
            logger.debug(f"Test-Ergebnis für {model_id}/{use_case}/{test_size} in MongoDB gespeichert")
            
        except ImportError:
            # Repository nicht verfügbar, überspringe Speicherung
            logger.debug("LLMTestResultRepository nicht verfügbar, überspringe MongoDB-Speicherung")
        except Exception as e:
            logger.warning(f"Fehler beim Speichern des Test-Ergebnisses in MongoDB: {str(e)}")

