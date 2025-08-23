"""
PDF-Handler für Secretary Job Worker.

Liest Parameter aus dem Job, führt PDF-Verarbeitung aus und speichert Results.
"""

from typing import Any, Dict, Optional, cast
import requests  # type: ignore
import os

from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.core.models.enums import ProcessingStatus
from src.processors.pdf_processor import PDFProcessor


async def handle_pdf_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
	# Sofort Debug-Log schreiben
	try:
		repo.add_log_entry(job.job_id, "info", f"PDF-Handler gestartet für Job {job.job_id}")
		
		params = getattr(job, "parameters", None)
		if not params:
			repo.add_log_entry(job.job_id, "error", "Keine Parameter im Job gefunden")
			raise ValueError("Keine Parameter im Job gefunden")

		# Extrahiere generische Felder aus Parameters; unterstütze sowohl lokale Datei als auch URL
		file_path: Optional[str] = getattr(params, "filename", None) or getattr(params, "url", None)
		# reduziert: keine Pfad-Details loggen
		
		if not file_path:
			# Fallback: einige Flows nutzen `parameters.extra.file_path`
			extra = getattr(params, "extra", {}) or {}
			file_path = str(extra.get("file_path", ""))
			# reduziert: keine zusätzlichen Pfad-Details
			
		if not file_path:
			repo.add_log_entry(job.job_id, "error", "Weder filename/url noch extra.file_path gesetzt")
			raise ValueError("Weder filename/url noch extra.file_path gesetzt")

		# Pfad normalisieren und kurz warten, falls Datei gerade geschrieben wird
		# Normalisieren: POSIX -> OS-spezifisch und absolut
		posix_path = file_path.replace('\\', '/')
		normalized_path = os.path.abspath(os.path.normpath(posix_path))
		# reduziert: keine Pfad-/Working-Dir-Details
		# Kurzer Retry: bis zu 0.5s warten (5x 100ms)
		import time
		file_exists = os.path.exists(normalized_path)
		if not file_exists:
			for _ in range(5):
				time.sleep(0.1)
				if os.path.exists(normalized_path):
					file_exists = True
					break
		repo.add_log_entry(job.job_id, "info", f"Datei existiert nach Retry: {file_exists}")
		
	except Exception as e:
		repo.add_log_entry(job.job_id, "error", f"Fehler in Handler-Init: {str(e)}")
		raise

	# Weitere optionale Parameter (nur flach)
	extraction_method: str = getattr(params, "extraction_method", None) or "native"
	template: Optional[str] = getattr(params, "template", None)
	context: Optional[Dict[str, Any]] = getattr(params, "context", None)
	use_cache: bool = bool(getattr(params, "use_cache", True))
	include_images: bool = bool(getattr(params, "include_images", False))

	processor = PDFProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

	# Fortschritt aktualisieren
	repo.update_job_status(
		job_id=job.job_id,
		status="processing",
		progress=JobProgress(step="downloading_or_opening", percent=5, message="Öffne Datei/URL"),
	)

	# Optionalen Progress-Callback senden (Client erwartet Zwischenstände)
	# Ermittelt Callback-URL und Token einmalig
	callback_url: Optional[str] = None
	callback_token: Optional[str] = None
	_client_job_id: Optional[str] = None
	webhook_any: Any = getattr(job.parameters, "webhook", None)
	if isinstance(webhook_any, dict):
		webhook_dict: Dict[str, Any] = cast(Dict[str, Any], webhook_any)
		url_val = webhook_dict.get("url")
		token_val = webhook_dict.get("token")
		jobid_val = webhook_dict.get("jobId")
		callback_url = url_val if isinstance(url_val, str) else None
		callback_token = token_val if isinstance(token_val, str) else None
		_client_job_id = jobid_val if isinstance(jobid_val, str) else None

	def _post_progress(phase: str, progress: int, message: str) -> None:
		if not callback_url:
			return
		headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
		if callback_token:
			headers["Authorization"] = f"Bearer {callback_token}"
			headers["X-Callback-Token"] = str(callback_token)
		payload: Dict[str, Any] = {
			"phase": phase,
			"progress": progress,
			"message": message,
			"process": {"id": job.job_id},
		}
		try:
			repo.add_log_entry(job.job_id, "info", f"Webhook-Progress: phase={phase} progress={progress}")
			requests.post(url=str(callback_url), json=payload, headers=headers, timeout=15)
		except Exception as _:
			# Progress-Fehler nicht fatal
			pass

	_post_progress("initializing", 5, "Job initialisiert")

	result = await processor.process(
		file_path=normalized_path,
		template=template,  # type: ignore
		context=context,
		extraction_method=extraction_method,  # type: ignore
		use_cache=use_cache,
		file_hash=None,
		include_images=include_images,
	)

	_post_progress("postprocessing", 95, "Ergebnisse werden gespeichert")

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

	# Volles Processor-Resultat zusätzlich in structured_data ablegen, damit API bei wait_ms direkt rückspiegeln kann
	to_dict_attr: Any = getattr(result, "to_dict", None)
	if callable(to_dict_attr):
		result_any: Any = to_dict_attr()
	else:
		result_any = {}
	result_dict: Dict[str, Any] = cast(Dict[str, Any], result_any) if isinstance(result_any, dict) else {}
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
			structured_data=result_dict,
			target_dir=process_dir,
			page_texts=[str(p) for p in text_paths],
			asset_dir=process_dir,
		),
	)

	# Webhook-Dispatch (final nach neuer Spezifikation)
	if callback_url:
		headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
		if callback_token:
			headers["Authorization"] = f"Bearer {callback_token}"
			headers["X-Callback-Token"] = str(callback_token)
		# Daten extrahieren für finales Event
		data_section: Dict[str, Any] = {}
		data_obj: Any = result_dict.get("data", {})
		if isinstance(data_obj, dict):
			if "extracted_text" in data_obj:
				data_section["extracted_text"] = data_obj.get("extracted_text")
			if "images_archive_data" in data_obj:
				data_section["images_archive_data"] = data_obj.get("images_archive_data")
			if "images_archive_filename" in data_obj:
				data_section["images_archive_filename"] = data_obj.get("images_archive_filename")
			meta: Dict[str, Any] = {}
			meta_src: Any = data_obj.get("metadata")
			if isinstance(meta_src, dict) and "text_contents" in meta_src:
				meta_src_dict: Dict[str, Any] = cast(Dict[str, Any], meta_src)
				meta["text_contents"] = meta_src_dict.get("text_contents")
			if meta:
				data_section["metadata"] = meta
		payload_final: Dict[str, Any] = {
			"phase": "completed",
			"message": "Extraktion abgeschlossen",
			"data": data_section,
		}
		try:
			repo.add_log_entry(job.job_id, "info", f"Sende Webhook-Callback an {callback_url}")
			resp = requests.post(url=str(callback_url), json=payload_final, headers=headers, timeout=30)
			repo.add_log_entry(job.job_id, "info", f"Webhook Antwort: {getattr(resp, 'status_code', None)} ok={getattr(resp, 'ok', None)}")
		except Exception as post_err:
			repo.add_log_entry(job.job_id, "error", f"Webhook-POST fehlgeschlagen: {str(post_err)}")


