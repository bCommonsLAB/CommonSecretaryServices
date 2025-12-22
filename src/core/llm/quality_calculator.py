"""
@fileoverview Quality Calculator - Calculates quality scores for LLM test results

@description
Calculates quality scores by comparing input and output embeddings using VoyageAI.
Computes cosine similarity between embeddings to measure semantic similarity.

@module core.llm.quality_calculator

@exports
- QualityCalculator: Class - Quality score calculation service
"""

import json
import math
import logging
from typing import Dict, List, Optional, Any, Tuple

from ..models.llm_test import LLMTestCase
from ..exceptions import ProcessingError
from .config_manager import LLMConfigManager
from .provider_manager import ProviderManager
from .use_cases import UseCase

logger = logging.getLogger(__name__)


class QualityCalculator:
    """
    Berechnet Qualitätsscores für LLM-Test-Ergebnisse.
    
    Verwendet Embeddings von VoyageAI, um die semantische Ähnlichkeit
    zwischen Input- und Output-Text zu messen.
    """
    
    def __init__(self) -> None:
        """Initialisiert den Quality Calculator."""
        self.config_manager = LLMConfigManager()
        self.provider_manager = ProviderManager()
        self._voyageai_provider: Optional[Any] = None
    
    def _get_voyageai_provider(self) -> Optional[Any]:
        """
        Lädt den VoyageAI Provider aus der Konfiguration.
        
        Returns:
            Optional[VoyageAIProvider]: VoyageAI Provider oder None wenn nicht verfügbar
        """
        if self._voyageai_provider is not None:
            return self._voyageai_provider
        
        try:
            # Lade VoyageAI Provider-Konfiguration
            provider_config = self.config_manager.get_provider_config('voyageai')
            if not provider_config or not provider_config.enabled:
                logger.warning("VoyageAI Provider nicht konfiguriert oder deaktiviert")
                return None
            
            # Prüfe API-Key
            if not provider_config.api_key or provider_config.api_key == 'not-configured':
                logger.warning("VoyageAI API-Key nicht konfiguriert")
                return None
            
            # Erstelle Provider-Instanz
            self._voyageai_provider = self.provider_manager.get_provider(
                provider_name='voyageai',
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                **provider_config.additional_config
            )
            
            return self._voyageai_provider
        except Exception as e:
            logger.error(f"Fehler beim Laden des VoyageAI Providers: {str(e)}")
            return None
    
    def _extract_input_text(self, test_case: LLMTestCase) -> str:
        """
        Extrahiert Input-Text aus Test-Case Parametern als JSON-String.
        
        Args:
            test_case: Der Test-Case mit Parametern
            
        Returns:
            str: JSON-String der Parameter
        """
        try:
            # Konvertiere alle Parameter zu JSON-String
            return json.dumps(test_case.parameters, ensure_ascii=False, sort_keys=True)
        except Exception as e:
            logger.error(f"Fehler beim Extrahieren des Input-Texts: {str(e)}")
            return ""
    
    def _extract_output_text(self, structured_data: Dict[str, Any]) -> str:
        """
        Konvertiert structured_data zu JSON-String.
        
        Args:
            structured_data: Das structured_data Dictionary
            
        Returns:
            str: JSON-String des structured_data
        """
        try:
            return json.dumps(structured_data, ensure_ascii=False, sort_keys=True)
        except Exception as e:
            logger.error(f"Fehler beim Extrahieren des Output-Texts: {str(e)}")
            return ""
    
    def _calculate_cosine_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> float:
        """
        Berechnet die Cosinus-Similarity zwischen zwei Embeddings.
        
        Args:
            embedding1: Erstes Embedding-Vektor
            embedding2: Zweites Embedding-Vektor
            
        Returns:
            float: Cosinus-Similarity zwischen 0.0 und 1.0
            
        Raises:
            ValueError: Wenn die Vektoren unterschiedliche Längen haben oder leer sind
        """
        if len(embedding1) != len(embedding2):
            raise ValueError(
                f"Embeddings haben unterschiedliche Längen: {len(embedding1)} vs {len(embedding2)}"
            )
        
        if len(embedding1) == 0:
            raise ValueError("Embeddings dürfen nicht leer sein")
        
        # Berechne Dot Product
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        
        # Berechne Magnitudes
        magnitude1 = math.sqrt(sum(a * a for a in embedding1))
        magnitude2 = math.sqrt(sum(b * b for b in embedding2))
        
        # Vermeide Division durch Null
        if magnitude1 == 0.0 or magnitude2 == 0.0:
            return 0.0
        
        # Berechne Cosinus-Similarity
        similarity = dot_product / (magnitude1 * magnitude2)
        
        # Stelle sicher, dass der Wert zwischen 0.0 und 1.0 liegt
        return max(0.0, min(1.0, similarity))
    
    def calculate_quality_score(
        self,
        test_case: LLMTestCase,
        structured_data: Dict[str, Any]
    ) -> Optional[Tuple[float, List[float], List[float]]]:
        """
        Berechnet den Quality Score durch Vergleich von Input- und Output-Embeddings.
        
        Args:
            test_case: Der Test-Case mit Input-Parametern
            structured_data: Das structured_data Dictionary aus der Response
            
        Returns:
            Optional[Tuple[float, List[float], List[float]]]: 
                Tuple aus (quality_score, input_embedding, output_embedding) oder None bei Fehler
        """
        try:
            # Lade VoyageAI Provider
            voyageai_provider = self._get_voyageai_provider()
            if not voyageai_provider:
                logger.warning("VoyageAI Provider nicht verfügbar, überspringe Quality-Berechnung")
                return None
            
            # Extrahiere Input- und Output-Text
            input_text = self._extract_input_text(test_case)
            output_text = self._extract_output_text(structured_data)
            
            if not input_text or not output_text:
                logger.warning("Input- oder Output-Text ist leer, überspringe Quality-Berechnung")
                return None
            
            # Lade Embedding-Modell aus Config
            embedding_model, _, _ = self.config_manager.get_embedding_defaults()
            if not embedding_model:
                # Fallback auf Standard-Modell
                embedding_model = "voyage-3-large"
            
            # Berechne Embeddings
            try:
                input_embeddings, _ = voyageai_provider.embedding(
                    texts=[input_text],
                    model=embedding_model,
                    input_type="document"
                )
                output_embeddings, _ = voyageai_provider.embedding(
                    texts=[output_text],
                    model=embedding_model,
                    input_type="document"
                )
            except Exception as e:
                logger.error(f"Fehler beim Berechnen der Embeddings: {str(e)}")
                return None
            
            if not input_embeddings or not output_embeddings:
                logger.warning("Embeddings konnten nicht berechnet werden")
                return None
            
            if len(input_embeddings) == 0 or len(output_embeddings) == 0:
                logger.warning("Embeddings-Listen sind leer")
                return None
            
            input_embedding = input_embeddings[0]
            output_embedding = output_embeddings[0]
            
            # Berechne Cosinus-Similarity
            try:
                quality_score = self._calculate_cosine_similarity(
                    input_embedding,
                    output_embedding
                )
            except Exception as e:
                logger.error(f"Fehler beim Berechnen der Cosinus-Similarity: {str(e)}")
                return None
            
            logger.debug(
                f"Quality Score berechnet: {quality_score:.4f} "
                f"(Input-Länge: {len(input_embedding)}, Output-Länge: {len(output_embedding)})"
            )
            
            return (quality_score, input_embedding, output_embedding)
            
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei der Quality-Berechnung: {str(e)}")
            return None

