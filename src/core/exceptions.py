"""
@fileoverview Exception Definitions - Central error handling for processing service

@description
Central exception definitions for Common Secretary Services. This file defines a
hierarchy of custom exceptions for various error scenarios.

Exception hierarchy:
- BaseProcessingException: Base exception with extended error details
  - RateLimitExceeded: Rate limit exceeded
  - FileSizeLimitExceeded: File size exceeded
  - ProcessingError: General processing errors
    - UnsupportedMimeTypeError: Unsupported MIME type
    - ContentExtractionError: Content extraction error
    - ValidationError: Validation error

All exceptions support optional details dictionaries for additional error information.

@module core.exceptions

@exports
- BaseProcessingException: Class - Base exception with details
- RateLimitExceeded: Class - Rate limit error
- FileSizeLimitExceeded: Class - File size error
- ProcessingError: Class - General processing error
- UnsupportedMimeTypeError: Class - MIME type error
- ContentExtractionError: Class - Extraction error
- ValidationError: Class - Validation error

@usedIn
- src.processors.pdf_processor: Uses ProcessingError for error handling
- src.processors.*: All processors use ProcessingError
- src.core.validation: Uses ValidationError
- API routes: Use exceptions for error responses

@dependencies
- Standard: typing - Type annotations
"""
from typing import Optional, Dict, Any

class BaseProcessingException(Exception):
    """
    Basis-Exception mit erweiterten Informationen.
    
    Attributes:
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialisiert die Exception.
        
        Args:
            message: Die Fehlermeldung
            details: Optionale Details zum Fehler
        """
        super().__init__(message)
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
        
    def __str__(self) -> str:
        """Gibt eine formatierte Fehlermeldung zurück."""
        if self.details:
            return f"{self.message} - Details: {self.details}"
        return self.message

class RateLimitExceeded(BaseProcessingException):
    """
    Wird ausgelöst, wenn das Rate Limit überschritten wurde.
    
    Attributes:
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails wie z.B. Wartezeit
    """
    
    def __init__(self, message: str = "Rate limit exceeded", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)

class FileSizeLimitExceeded(BaseProcessingException):
    """
    Wird ausgelöst, wenn die maximale Dateigröße überschritten wurde.
    
    Attributes:
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails wie z.B. aktuelle und maximale Größe
    """
    
    def __init__(self, message: str = "File size limit exceeded", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)

class ProcessingError(BaseProcessingException):
    """
    Basis-Exception für Verarbeitungsfehler.
    
    Attributes:
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails zum Verarbeitungsfehler
    """
    
    def __init__(self, message: str = "Processing error occurred", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)

class UnsupportedMimeTypeError(ProcessingError):
    """
    Wird ausgelöst, wenn ein nicht unterstützter MIME-Type verarbeitet werden soll.
    
    Attributes:
        mime_type: Der nicht unterstützte MIME-Type
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails
    """
    
    def __init__(self, mime_type: str, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        self.mime_type: str = mime_type
        message = message or f"Unsupported MIME type: {mime_type}"
        super().__init__(message, details or {"mime_type": mime_type})

class ContentExtractionError(ProcessingError):
    """
    Wird ausgelöst, wenn bei der Extraktion von Inhalten ein Fehler auftritt.
    
    Attributes:
        source: Die Quelle, aus der extrahiert werden sollte
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails
    """
    
    def __init__(self, source: str, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        self.source: str = source
        message = message or f"Content extraction failed for: {source}"
        super().__init__(message, details or {"source": source})

class ValidationError(ProcessingError):
    """
    Wird ausgelöst, wenn die Validierung fehlschlägt.
    
    Attributes:
        field: Das Feld, das die Validierung nicht bestanden hat
        message: Die Fehlermeldung als String
        details: Ein Dictionary mit zusätzlichen Fehlerdetails
    """
    
    def __init__(self, field: str, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> None:
        self.field: str = field
        message = message or f"Validation failed for field: {field}"
        super().__init__(message, details or {"field": field}) 