"""
@fileoverview Audio Diarized Route - POST /api/audio/process-diarized

@description
Datei-Transkription MIT Sprecher-Erkennung. Eigener Endpunkt statt Schalter an
``/audio/process``, weil es ein anderer Vertrag ist:

| | /audio/process | /audio/process-diarized |
|---|---|---|
| Antwort | ein Volltext | ``segments`` mit ``speaker``, ``start``, ``end``, ``text`` |
| prompt / keywords | ja | nein — werden als ``dropped_context`` gemeldet |
| Uebersetzung / Template | ja | nein |
| Modell | Use-Case ``transcription`` | Use-Case ``diarized_transcription`` |

Stuecke bis 20 Minuten an Sprechpausen; Anbieter-Grenzen 25 MB und 1500 s je Anfrage.
Sync (ohne ``callback_url``) oder async als Job ``audio`` mit ``mode=diarized``.

@module api.routes.audio_diarized_routes

@usedIn
- src.api.routes.__init__: importiert dieses Modul, damit die Route am audio_ns haengt
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union, cast

from flask import request
from flask_restx import Resource, fields, inputs
from werkzeug.datastructures import FileStorage

from src.api.routes.audio_routes import (
    audio_ns,
    build_transcription_context,
    error_model,
    get_audio_processor,
)
from src.core.exceptions import ProcessingError
from src.core.llm.diarized_transcription import NO_MODEL_CONFIGURED, PROVIDER_UNSUPPORTED
from src.core.mongodb import SecretaryJobRepository
from src.processors.audio_cache_key import MODE_DIARIZED
from src.processors.diarized_audio_processor import DiarizedAudioProcessor
from src.utils.logger import get_logger

logger = get_logger(process_id="audio-diarized-api")

SUPPORTED_FORMATS = {'flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'opus', 'wav', 'webm'}

diarized_parser = audio_ns.parser()
diarized_parser.add_argument('file', location='files', type=FileStorage, required=True, help='Audio-Datei (multipart/form-data)')
diarized_parser.add_argument('source_language', location='form', type=str, default='auto', help='Sprache der Aufnahme (ISO 639-1) oder "auto"')
diarized_parser.add_argument('prompt', location='form', type=str, required=False, help='Wird vom Sprecher-Modell NICHT angenommen; erscheint in dropped_context')
diarized_parser.add_argument('keywords', location='form', type=str, required=False, help='Wird vom Sprecher-Modell NICHT angenommen; erscheint in dropped_context')
diarized_parser.add_argument('languages', location='form', type=str, required=False, help='Moegliche Sprachen (kommagetrennt oder JSON-Liste)')
diarized_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')
diarized_parser.add_argument('callback_url', location='form', type=str, required=False, help='Optional: Webhook-URL fuer asynchrone Verarbeitung')
diarized_parser.add_argument('callback_token', location='form', type=str, required=False, help='Optional: Token fuer Webhook-Auth')
diarized_parser.add_argument('jobId', location='form', type=str, required=False, help='Optional: Externe Job-ID (vom Client)')

diarized_response = audio_ns.model('DiarizedAudioResponse', {
    'output_text': fields.String(description='Markdown: ein Absatz je Sprecherwechsel mit **Label:**-Praefix'),
    'original_text': fields.String(description='Identisch mit output_text (keine Uebersetzung in diesem Modus)'),
    'speakers': fields.List(fields.String, description='Alle Labels in Reihenfolge des ersten Auftretens'),
    'segments': fields.List(fields.Raw, description='[{speaker, start, end, text}] mit absoluten Sekunden'),
    'detected_language': fields.String(description='Erkannte Sprache (ISO 639-1) oder "auto"'),
    'duration': fields.Float(description='Dauer der Aufnahme in Sekunden'),
    'llm_model': fields.String(description='Modell aus der Maske (Use-Case diarized_transcription)'),
    'chunk_count': fields.Integer(description='Anzahl Stuecke (0 bei Cache-Treffer)'),
    'dropped_context': fields.List(fields.String, description='Verworfene Kontextfelder mit Begruendung'),
    'from_cache': fields.Boolean(description='Ergebnis aus dem Cache'),
})

_ERROR_STATUS = {NO_MODEL_CONFIGURED: 503, PROVIDER_UNSUPPORTED: 503}


def _error(code: str, message: str, status: int, details: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    return {'status': 'error', 'error': {'code': code, 'message': message, 'details': details}}, status


@audio_ns.route('/process-diarized')
class AudioProcessDiarizedEndpoint(Resource):
    """Datei-Transkription mit Sprecher-Erkennung."""

    @audio_ns.expect(diarized_parser)
    @audio_ns.response(200, 'Erfolg', diarized_response)
    @audio_ns.response(400, 'Validierungsfehler', error_model)
    @audio_ns.response(503, 'Kein Modell fuer diarized_transcription zugeordnet', error_model)
    @audio_ns.doc(description=(
        'Transkribiert eine Audio-Datei mit Sprecher-Labels (response_format diarized_json, '
        'chunking_strategy auto). Stuecke bis 20 Minuten an Sprechpausen; Labels je Stueck '
        'eindeutig. prompt und keywords nimmt das Modell nicht an und werden als dropped_context gemeldet.'
    ))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        if not request.content_type or 'multipart/form-data' not in request.content_type:
            return _error('INVALID_CONTENT_TYPE', 'Content-Type muss multipart/form-data sein', 400)
        try:
            args = cast(Dict[str, Any], diarized_parser.parse_args())
        except Exception as parse_error:
            return _error('PARSE_ERROR', 'Fehler beim Parsen der Request-Daten', 400,
                          {'error_type': type(parse_error).__name__, 'error_message': str(parse_error)})

        audio_file = cast(Optional[FileStorage], args.get('file'))
        if not audio_file:
            return _error('MISSING_FILE', 'Keine Audio-Datei gefunden', 400)

        file_ext = Path(str(audio_file.filename or '').lower()).suffix.lstrip('.')
        if file_ext not in SUPPORTED_FORMATS:
            return _error('INVALID_FORMAT',
                          f"Das Format '{file_ext}' wird nicht unterstützt. Unterstützte Formate: {', '.join(sorted(SUPPORTED_FORMATS))}",
                          400, {'supported_formats': sorted(SUPPORTED_FORMATS)})

        source_language = str(args.get('source_language') or 'auto')
        use_cache = bool(args.get('useCache', True))
        context = build_transcription_context(args, source_language)
        callback_url = str(args.get('callback_url') or '') or None
        callback_token = str(args.get('callback_token') or '') or None
        job_id_form = str(args.get('jobId') or '').strip() or None
        source_info = {
            'original_filename': audio_file.filename,
            'file_size': getattr(audio_file, 'content_length', None),
            'file_type': audio_file.content_type,
            'file_ext': file_ext,
        }

        if callback_url:
            return self._enqueue(audio_file, source_info, source_language, use_cache, context,
                                 callback_url, callback_token, job_id_form)

        temp_path: Optional[str] = None
        try:
            processor = DiarizedAudioProcessor(get_audio_processor().resource_calculator, process_id=str(uuid.uuid4()))
            temp_file, temp_path = processor.get_upload_temp_file(suffix=f'.{file_ext}')
            audio_file.save(temp_path)
            temp_file.close()
            response = asyncio.run(processor.process_diarized(
                audio_source=temp_path, source_info=source_info, source_language=source_language,
                use_cache=use_cache, transcription_context=context,
            ))
            return response.to_dict()
        except ProcessingError as e:
            code = str((getattr(e, 'details', None) or {}).get('error_code') or type(e).__name__)
            logger.error('Sprecher-Transkription fehlgeschlagen', error=e, code=code)
            return _error(code, str(e), _ERROR_STATUS.get(code, 400), getattr(e, 'details', None))
        except Exception as e:
            logger.error('Unerwarteter Fehler bei der Sprecher-Transkription', error=e)
            return _error('INTERNAL_ERROR', 'Ein unerwarteter Fehler ist aufgetreten', 500,
                          {'error_type': type(e).__name__, 'error_message': str(e)})
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _enqueue(self, audio_file: FileStorage, source_info: Dict[str, Any], source_language: str,
                 use_cache: bool, context: Any, callback_url: str, callback_token: Optional[str],
                 job_id_form: Optional[str]) -> Tuple[Dict[str, Any], int]:
        """Async wie /audio/process: Job 'audio' mit mode=diarized, Antwort 202."""
        process_id = str(uuid.uuid4())
        upload_dir = Path('cache') / 'uploads'
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(audio_file.filename).suffix if audio_file.filename else '.audio'
        upload_path = Path(os.path.abspath(upload_dir / f'upload_{uuid.uuid4()}{suffix}')).as_posix()
        audio_file.save(upload_path)

        params: Dict[str, Any] = {
            'filename': upload_path,
            'use_cache': use_cache,
            'source_language': source_language,
            'target_language': source_language,
            'template': None,
            'mode': MODE_DIARIZED,
            'context': {**source_info, 'original_filename': audio_file.filename},
            'transcription_context': context.to_dict(),
            'webhook': {'url': callback_url, 'token': callback_token, 'jobId': job_id_form},
        }
        created_job_id = SecretaryJobRepository().create_job({'job_type': 'audio', 'parameters': params})
        logger.info('Webhook-ACK gesendet (Audio-Job diarized enqueued)', process_id=process_id,
                    job_id_external=job_id_form, job_id_internal=created_job_id, callback_url=callback_url)
        return {
            'status': 'accepted', 'worker': 'secretary',
            'process': {'id': process_id, 'main_processor': 'audio', 'mode': MODE_DIARIZED,
                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'is_from_cache': False},
            'job': {'id': job_id_form or created_job_id},
            'webhook': {'delivered_to': callback_url},
            'error': None,
        }, 202
