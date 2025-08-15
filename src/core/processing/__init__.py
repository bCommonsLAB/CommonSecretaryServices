"""Initialisierung der Processing-Registry und Standard-Handler."""

from .registry import register, get_handler, available_job_types  # re-export

# Standard-Handler registrieren (on import)
try:
    from .handlers.pdf_handler import handle_pdf_job
    register("pdf", handle_pdf_job)
except Exception:  # defensive, Registry muss auch ohne PDF funktionieren
    pass

__all__ = ["register", "get_handler", "available_job_types"]


