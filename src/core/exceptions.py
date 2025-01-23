class RateLimitExceeded(Exception):
    """Wird ausgelöst, wenn das Rate Limit überschritten wurde"""
    pass

class FileSizeLimitExceeded(Exception):
    """Wird ausgelöst, wenn die maximale Dateigröße überschritten wurde"""
    pass

class ProcessingError(Exception):
    """Basis-Exception für Verarbeitungsfehler"""
    pass

class UnsupportedMimeTypeError(ProcessingError):
    """Wird ausgelöst, wenn ein nicht unterstützter MIME-Type verarbeitet werden soll"""
    pass

class ContentExtractionError(ProcessingError):
    """Wird ausgelöst, wenn bei der Extraktion von Inhalten ein Fehler auftritt"""
    pass

class ValidationError(ProcessingError):
    """Wird ausgelöst, wenn die Validierung fehlschlägt"""
    pass 