"""
@fileoverview LLM Model Selector - Intelligente Modellauswahl basierend auf Test-Ergebnissen

@description
Wählt das beste Modell für einen Use-Case basierend auf gespeicherten Test-Ergebnissen aus.
Berücksichtigt verschiedene Kriterien wie Dauer, Token-Verbrauch oder Zuverlässigkeit.

@module core.llm.model_selector

@exports
- LLMModelSelector: Class - Intelligente Modellauswahl
"""

from typing import Optional
import logging

from ..mongodb.llm_model_repository import LLMTestResultRepository, LLMUseCaseConfigRepository
from .config_manager import LLMConfigManager

logger = logging.getLogger(__name__)


class LLMModelSelector:
    """
    Wählt das beste Modell für einen Use-Case basierend auf Test-Ergebnissen aus.
    """
    
    def __init__(self) -> None:
        """Initialisiert den Model Selector."""
        self.test_result_repo = LLMTestResultRepository()
        self.use_case_config_repo = LLMUseCaseConfigRepository()
        self.config_manager = LLMConfigManager()
    
    def get_best_model_for_use_case(
        self,
        use_case: str,
        test_size: str,
        criteria: str = "duration"
    ) -> Optional[str]:
        """
        Gibt das beste Modell für einen Use-Case basierend auf Test-Ergebnissen zurück.
        
        Args:
            use_case: Der Use-Case
            test_size: Die Test-Größe ("small", "medium", "large")
            criteria: Kriterium für "beste" ("duration", "tokens", "reliability")
            
        Returns:
            Optional[str]: Die Modell-ID des besten Modells oder None
        """
        if criteria not in ["duration", "tokens", "reliability"]:
            logger.warning(f"Unbekanntes Kriterium {criteria}, verwende 'duration'")
            criteria = "duration"
        
        try:
            # Verwende Repository-Methode für Best-Model-Auswahl
            best_model_id = self.test_result_repo.get_best_model_for_use_case(
                use_case=use_case,
                test_size=test_size,
                criteria=criteria
            )
            
            if best_model_id:
                logger.debug(
                    f"Bestes Modell für {use_case}/{test_size} ({criteria}): {best_model_id}"
                )
                return best_model_id
            
            # Fallback: Verwende aktuelles Modell
            current_model_id = self.use_case_config_repo.get_current_model(use_case)
            if current_model_id:
                logger.debug(
                    f"Keine Test-Ergebnisse gefunden, verwende aktuelles Modell für {use_case}: {current_model_id}"
                )
                return current_model_id
            
            # Letzter Fallback: Verwende config.yaml
            use_case_config = self.config_manager.get_use_case_config(use_case)
            if use_case_config:
                fallback_model_id = f"{use_case_config.provider}/{use_case_config.model}"
                logger.debug(
                    f"Keine MongoDB-Konfiguration, verwende config.yaml für {use_case}: {fallback_model_id}"
                )
                return fallback_model_id
            
            return None
            
        except Exception as e:
            logger.error(f"Fehler bei der Best-Model-Auswahl für {use_case}: {str(e)}")
            return None

