"""
Factory für die standardisierte Erstellung von API-Responses.
"""
from datetime import datetime
from typing import Any, Dict, Optional, TypeVar, Type

from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .llm import LLMInfo
from .enums import ProcessingStatus

T = TypeVar('T', bound=BaseResponse)

class ResponseFactory:
    """Factory für die standardisierte Erstellung von API-Responses."""
    
    @staticmethod
    def create_response(
        processor_name: str,
        result: Any,
        request_info: Dict[str, Any],
        response_class: Type[T],
        llm_info: Optional[LLMInfo] = None,
        error: Optional[ErrorInfo] = None
    ) -> T:
        """
        Erstellt eine standardisierte Response mit LLM-Tracking.
        
        Args:
            processor_name: Name des Processors
            result: Das Ergebnis der Verarbeitung
            request_info: Request-Parameter
            response_class: Die zu erstellende Response-Klasse
            llm_info: Optional, LLM-Nutzungsinformationen
            error: Optional, Fehlerinformationen
            
        Returns:
            T: Die standardisierte Response vom angegebenen Typ
        """
        # Erstelle ProcessInfo
        process_info = ProcessInfo(
            id=processor_name,  # ID wird vom Processor gesetzt
            main_processor=processor_name,
            started=datetime.now().isoformat()
        )

        # Füge LLM-Info hinzu wenn vorhanden
        if llm_info is not None:
            process_info.add_llm_requests(llm_info)
            
        # Erstelle die Response
        response = response_class(
            request=RequestInfo(
                processor=processor_name,
                timestamp=datetime.now().isoformat(),
                parameters=request_info
            ),
            process=process_info,
            status=ProcessingStatus.ERROR if error else ProcessingStatus.SUCCESS,
            error=error,
            data=result
        )
            
        return response 