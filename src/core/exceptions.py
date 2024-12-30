class RateLimitExceeded(Exception):
    """Wird ausgelöst, wenn das Rate Limit überschritten wurde"""
    pass

class FileSizeLimitExceeded(Exception):
    """Wird ausgelöst, wenn die maximale Dateigröße überschritten wurde"""
    pass

class ProcessingError(Exception):
    """Basis-Exception für Verarbeitungsfehler"""
    pass 