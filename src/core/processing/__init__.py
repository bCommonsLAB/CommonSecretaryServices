"""Initialisierung der Processing-Registry und Standard-Handler."""

from .registry import register, get_handler, available_job_types  # re-export

# Standard-Handler registrieren (on import)
try:
    from .handlers.pdf_handler import handle_pdf_job
    register("pdf", handle_pdf_job)
except Exception:  # defensive, Registry muss auch ohne PDF funktionieren
    pass

try:
    from .handlers.session_handler import handle_session_job
    register("session", handle_session_job)
except Exception:
    pass

try:
    from .handlers.transformer_handler import handle_transformer_template_job
    register("transformer_template", handle_transformer_template_job)
except Exception:
    pass

__all__ = ["register", "get_handler", "available_job_types"]


