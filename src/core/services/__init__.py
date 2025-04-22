"""
Service-Modul mit zentralen Diensten für die Anwendung.
"""

try:
    from .translator_service import get_translator_service
except ImportError:
    pass

__all__ = ['get_translator_service'] 