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

try:
    from .handlers.office_handler import handle_office_job
    register("office", handle_office_job)
except Exception:
    pass

try:
    from .handlers.office_via_pdf_handler import handle_office_via_pdf_job
    register("office_via_pdf", handle_office_via_pdf_job)
except Exception:
    pass

try:
    # Audio async über den generischen Job-Worker (analog zu PDF)
    from .handlers.audio_handler import handle_audio_job
    register("audio", handle_audio_job)
except Exception:
    # defensive: Registry muss auch ohne Audio funktionieren
    pass

__all__ = ["register", "get_handler", "available_job_types"]


