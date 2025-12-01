"""
@fileoverview RAG API Routes - Flask-RESTX endpoint für RAG Embeddings

@description
RAG Processor API routes. Enthält den Endpoint für RAG-Embedding-Operationen
auf Basis von reinem Markdown-Text (ohne Datei-Upload oder Query-Funktion).

Main endpoint:
- POST /api/rag/embed-text: Embed markdown documents (als Text) und gibt Chunks
  mit Embeddings zurück (ohne Speicherung im Backend)

Features:
- Markdown-Text-Embedding mit voyage-3-large (oder konfiguriertem Modell)
- Rückgabe aller Chunks inkl. Embeddings an den Client
- Swagger UI documentation

@module api.routes.rag_routes

@exports
- rag_ns: Namespace - Flask-RESTX namespace for RAG endpoints

@usedIn
- src.api.routes.__init__: Registers rag_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- Internal: src.processors.rag_processor - RAGProcessor
- Internal: src.core.models.rag - RAG models (RAGResponse, etc.)
- Internal: src.core.exceptions - ProcessingError
- Internal: src.utils.logger - Logging system
"""
# pyright: reportMissingImports=false, reportUnknownMemberType=false

from flask_restx import Model, Namespace, OrderedModel, Resource, fields
from typing import Dict, Any, Union, Optional
import asyncio
import uuid

from src.processors.rag_processor import RAGProcessor
from src.core.models.rag import RAGResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger, ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="rag-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
rag_ns = Namespace('rag', description='RAG-Verarbeitungs-Operationen')

# Parser für Embed-Text-Parameter (Form-basierte Eingabe im Swagger-UI)
embed_text_parser = rag_ns.parser()
embed_text_parser.add_argument(
    'markdown',
    type=str,
    location='form',
    required=False,
    help='Markdown-Text, der gechunked und eingebettet werden soll (bei form-data)'
)
embed_text_parser.add_argument(
    'document_id',
    type=str,
    location='form',
    required=False,
    help='Optionale Dokument-ID (wird generiert wenn nicht angegeben)'
)
embed_text_parser.add_argument(
    'chunk_size',
    type=int,
    location='form',
    required=False,
    help='Chunk-Größe in Zeichen (Standard aus Config)'
)
embed_text_parser.add_argument(
    'chunk_overlap',
    type=int,
    location='form',
    required=False,
    help='Chunk-Overlap in Zeichen (Standard aus Config)'
)
embed_text_parser.add_argument(
    'embedding_model',
    type=str,
    location='form',
    required=False,
    help='Optionales Embedding-Modell (Standard aus LLM-Config/Processor)'
)
embed_text_parser.add_argument(
    'embedding_dimensions',
    type=int,
    location='form',
    required=False,
    help='Optionale Embedding-Dimensionen (Standard aus Config, z.B. 256, 512, 1024, 2048)'
)
embed_text_parser.add_argument(
    'metadata',
    type=str,
    location='form',
    required=False,
    help='Optionale Metadaten als JSON-String'
)

# Error-Modell
error_model: Model | OrderedModel = rag_ns.model('Error', {
    'status': fields.String(description='Status der Anfrage (error)'),
    'error': fields.Nested(rag_ns.model('ErrorDetails', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Zusätzliche Fehlerdetails')
    }))
})

# Response-Modelle
embedding_response: Model | OrderedModel = rag_ns.model('EmbeddingResponse', {
    'status': fields.String(description='Status der Anfrage'),
    'request': fields.Raw(description='Request-Informationen'),
    'process': fields.Raw(description='Prozess-Informationen'),
    'data': fields.Nested(rag_ns.model('EmbeddingData', {
        'document_id': fields.String(description='Dokument-ID'),
        'chunks': fields.List(fields.Raw, description='Liste der Chunks'),
        'total_chunks': fields.Integer(description='Gesamtanzahl der Chunks'),
        'embedding_dimensions': fields.Integer(description='Embedding-Dimensionen'),
        'embedding_model': fields.String(description='Verwendetes Embedding-Modell'),
        'created_at': fields.String(description='Erstellungszeitpunkt'),
        'metadata': fields.Raw(description='Metadaten')
    }))
})

# Helper-Funktion zum Abrufen des RAG-Prozessors
def get_rag_processor(process_id: Optional[str] = None) -> RAGProcessor:
    """Get or create RAG processor instance with process ID"""
    return RAGProcessor(
        resource_calculator,
        process_id=process_id or str(uuid.uuid4())
    )


# Embed-Text-Endpunkt (ohne Speicherung in MongoDB)
@rag_ns.route('/embed-text')
class RAGEmbedTextEndpoint(Resource):
    """RAG Embedding-Endpunkt für reinen Markdown-Text ohne MongoDB-Speicherung."""
    
    @rag_ns.expect(embed_text_parser)
    @rag_ns.response(200, 'Erfolg', embedding_response)
    @rag_ns.response(400, 'Validierungsfehler', error_model)
    @rag_ns.doc(description='Betten Markdown-Text ein und geben Chunks + Embeddings ohne Speicherung zurück.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Betten Markdown-Text ein, ohne die Ergebnisse in MongoDB zu speichern."""
        try:
            from flask import request
            import json
            
            # Unterstütze sowohl JSON-Body als auch form-data (wie bei transformer_routes)
            if request.is_json:
                raw: Dict[str, Any] = request.get_json(silent=True) or {}
                markdown_text: Optional[str] = raw.get('markdown')
                document_id: Optional[str] = raw.get('document_id')
                chunk_size: Optional[int] = raw.get('chunk_size')
                chunk_overlap: Optional[int] = raw.get('chunk_overlap')
                embedding_model: Optional[str] = raw.get('embedding_model')
                embedding_dimensions: Optional[int] = raw.get('embedding_dimensions')
                raw_metadata: Union[Dict[str, Any], str, None] = raw.get('metadata') or {}
            else:
                args: Dict[str, Any] = embed_text_parser.parse_args()  # type: ignore
                markdown_text: Optional[str] = args.get('markdown')  # type: ignore
                document_id: Optional[str] = args.get('document_id')  # type: ignore
                chunk_size: Optional[int] = args.get('chunk_size')  # type: ignore
                chunk_overlap: Optional[int] = args.get('chunk_overlap')  # type: ignore
                embedding_model: Optional[str] = args.get('embedding_model')  # type: ignore
                embedding_dimensions: Optional[int] = args.get('embedding_dimensions')  # type: ignore
                raw_metadata: Union[Dict[str, Any], str, None] = args.get('metadata') or {}  # type: ignore
            
            # Validierung: Markdown muss vorhanden sein
            if not markdown_text or not isinstance(markdown_text, str) or not markdown_text.strip():
                return {
                    'status': 'error',
                    'error': {
                        'code': 'MISSING_MARKDOWN',
                        'message': 'Feld \"markdown\" mit nicht-leerem Text ist erforderlich',
                        'details': {}
                    }
                }, 400
            
            # Metadaten parsen
            metadata: Dict[str, Any]
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
            else:
                try:
                    parsed: Any = json.loads(str(raw_metadata))  # type: ignore
                    metadata = parsed if isinstance(parsed, dict) else {'client_metadata': raw_metadata}  # type: ignore
                except Exception:
                    metadata = {'client_metadata': raw_metadata}
            
            # Prozessor initialisieren
            process_id = str(uuid.uuid4())
            processor = get_rag_processor(process_id)
            
            # Embedding durchführen (ohne Speicherung)
            # Typ-Annotationen für Parameter (markdown_text ist bereits validiert, daher nicht None)
            embedding_result = asyncio.run(
                processor.embed_document_for_client(
                    text=str(markdown_text),  # Nach Validierung sicher str
                    document_id=document_id if document_id else None,  # type: ignore
                    chunk_size=chunk_size if chunk_size is not None else None,  # type: ignore
                    chunk_overlap=chunk_overlap if chunk_overlap is not None else None,  # type: ignore
                    embedding_model=embedding_model if embedding_model else None,  # type: ignore
                    embedding_dimensions=embedding_dimensions if embedding_dimensions is not None else None,  # type: ignore
                    metadata=metadata  # type: ignore
                )
            )
            
            # Response erstellen
            response = processor.create_response(
                processor_name="rag",
                result=embedding_result,
                request_info={
                    'endpoint': 'embed_text',
                    'document_id': embedding_result.document_id,
                    'chunk_size': chunk_size,
                    'chunk_overlap': chunk_overlap,
                    'input_length': len(markdown_text),
                    'embedding_model': embedding_model or embedding_result.embedding_model,
                    'embedding_dimensions': embedding_dimensions or embedding_result.embedding_dimensions,
                    'client_metadata_present': bool(metadata)
                },
                response_class=RAGResponse,
                from_cache=False,
                cache_key=""
            )
            
            return response.to_dict()
        
        except ProcessingError as e:
            logger.error("RAG Embedding-Text-Fehler", error=e)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': getattr(e, 'details', None)
                }
            }, 400
        
        except Exception as e:
            logger.error("Unerwarteter Fehler bei RAG Embedding-Text", error=e)
            return {
                'status': 'error',
                'error': {
                    'code': 'INTERNAL_ERROR',
                    'message': 'Ein unerwarteter Fehler ist aufgetreten',
                    'details': {
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                }
            }, 500

