"""
Session-Handler für Secretary Job Worker.

Nutzt den bestehenden SessionProcessor, um Sessions zu verarbeiten.
"""

from typing import Any, List

from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.processors.session_processor import SessionProcessor


async def handle_session_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    # Pflichtfelder prüfen
    event = str(getattr(params, "event", "") or "")
    session = str(getattr(params, "session", "") or "")
    if not event or not session:
        raise ValueError("Pflichtfelder 'event' und 'session' müssen gesetzt sein")

    # Optionale Parameter extrahieren
    url = str(getattr(params, "url", "") or "")
    filename = str(getattr(params, "filename", "") or "")
    track = str(getattr(params, "track", "") or "")
    day = getattr(params, "day", None)
    starttime = getattr(params, "starttime", None)
    endtime = getattr(params, "endtime", None)
    speakers: List[str] = list(getattr(params, "speakers", []) or [])
    video_url = str(getattr(params, "video_url", "") or "")
    attachments_url = str(getattr(params, "attachments_url", "") or "")
    source_language = str(getattr(params, "source_language", "en") or "en")
    target_language = str(getattr(params, "target_language", "de") or "de")
    use_cache: bool = bool(getattr(params, "use_cache", True))

    # create_archive in extra erlaubt überschreiben
    create_archive = bool(getattr(params, "create_archive", getattr(params, "extra", {}).get("create_archive", True)))  # type: ignore

    processor = SessionProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

    # Fortschritt aktualisieren
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="processing", percent=20, message="Session-Verarbeitung gestartet"),
    )

    result = await processor.process_session(
        event=event,
        session=session,
        url=url,
        filename=filename,
        track=track,
        day=day,
        starttime=starttime,
        endtime=endtime,
        speakers=speakers,
        video_url=video_url,
        attachments_url=attachments_url,
        source_language=source_language,
        target_language=target_language,
        use_cache=use_cache,
        create_archive=create_archive,
    )

    # Ergebnis entpacken
    data = getattr(result, 'data', None)
    output = getattr(data, 'output', None) if data else None
    if not output:
        raise RuntimeError("Keine Ausgabedaten vom SessionProcessor erhalten")

    markdown_file = getattr(output, 'markdown_file', None)
    markdown_content = getattr(output, 'markdown_content', None)
    assets = getattr(output, 'attachments', []) or []
    web_text = getattr(output, 'web_text', None)
    video_transcript = getattr(output, 'video_transcript', None)
    attachments_text = getattr(output, 'attachments_text', None)
    attachments_url_out = getattr(output, 'attachments_url', None)
    archive_data = getattr(output, 'archive_data', None)
    archive_filename = getattr(output, 'archive_filename', None)
    structured_data = getattr(output, 'structured_data', None)
    target_dir = getattr(output, 'target_dir', None)
    page_texts = getattr(output, 'page_texts', []) or []
    asset_dir = getattr(output, 'asset_dir', None)

    # Fortschritt/Ergebnisse speichern
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
        results=JobResults(
            markdown_file=markdown_file,
            markdown_content=markdown_content,
            assets=assets,
            web_text=web_text,
            video_transcript=video_transcript,
            attachments_text=attachments_text,
            attachments_url=attachments_url_out,
            archive_data=archive_data,
            archive_filename=archive_filename,
            structured_data=structured_data,
            target_dir=target_dir,
            page_texts=page_texts,
            asset_dir=asset_dir,
        ),
    )


