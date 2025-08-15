"""
PDF-Handler für Secretary Job Worker.

Liest Parameter aus dem Job, führt PDF-Verarbeitung aus und speichert Results.
"""

from typing import Any, Dict, Optional

from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.core.models.enums import ProcessingStatus
from src.processors.pdf_processor import PDFProcessor


async def handle_pdf_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
	params = getattr(job, "parameters", None)
	if not params:
		raise ValueError("Keine Parameter im Job gefunden")

	# Extrahiere generische Felder aus Parameters; unterstütze sowohl lokale Datei als auch URL
	file_path: Optional[str] = getattr(params, "filename", None) or getattr(params, "url", None)
	if not file_path:
		# Fallback: einige Flows nutzen `parameters.extra.file_path`
		extra = getattr(params, "extra", {}) or {}
		file_path = str(extra.get("file_path", ""))
	if not file_path:
		raise ValueError("Weder filename/url noch extra.file_path gesetzt")

	# Weitere optionale Parameter
	extraction_method: str = getattr(params, "extraction_method", None) or (getattr(params, "extra", {}) or {}).get("extraction_method", "native")  # type: ignore
	template: Optional[str] = getattr(params, "template", None) or (getattr(params, "extra", {}) or {}).get("template")  # type: ignore
	context: Optional[Dict[str, Any]] = getattr(params, "context", None) or (getattr(params, "extra", {}) or {}).get("context")  # type: ignore
	use_cache: bool = bool(getattr(params, "use_cache", True))
	include_images: bool = bool((getattr(params, "extra", {}) or {}).get("include_images", False))

	processor = PDFProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

	# Fortschritt aktualisieren
	repo.update_job_status(
		job_id=job.job_id,
		status="processing",
		progress=JobProgress(step="downloading_or_opening", percent=5, message="Öffne Datei/URL"),
	)

	result = await processor.process(
		file_path=file_path,
		template=template,  # type: ignore
		context=context,
		extraction_method=extraction_method,  # type: ignore
		use_cache=use_cache,
		file_hash=None,
		include_images=include_images,
	)

	# Fehlerpfad: Response mit Status ERROR → Exception werfen, damit Manager FAILED setzt
	status_value = getattr(result, "status", None)
	if status_value == ProcessingStatus.ERROR:
		err = getattr(result, "error", None)
		err_msg = getattr(err, "message", "PDF-Verarbeitung fehlgeschlagen")
		err_code = getattr(err, "code", "PROCESSING_ERROR")
		raise RuntimeError(f"{err_code}: {err_msg}")

	# Ergebnisse in Job speichern
	data = getattr(result, "data", None)
	if not data:
		raise RuntimeError("Keine Daten vom PDFProcessor")

	# Defensiv Metadaten extrahieren
	metadata = getattr(data, "metadata", None)
	image_paths = getattr(metadata, "image_paths", []) if metadata else []
	process_dir = getattr(metadata, "process_dir", None) if metadata else None
	text_paths = getattr(metadata, "text_paths", []) if metadata else []

	repo.update_job_status(
		job_id=job.job_id,
		status="processing",
		progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
		results=JobResults(
			markdown_file=None,
			markdown_content=None,
			assets=[str(p) for p in image_paths],
			web_text=None,
			video_transcript=None,
			attachments_text=None,
			context=None,
			attachments_url=None,
			archive_data=getattr(data, "images_archive_data", None),
			archive_filename=getattr(data, "images_archive_filename", None),
			structured_data=None,
			target_dir=process_dir,
			page_texts=[str(p) for p in text_paths],
			asset_dir=process_dir,
		),
	)


