# Code Index

Automatically generated index of all documented Python files.

## Overview

Total: 105 documented files

## Entry Points

| File | Module | Description | Exports |
|------|--------|-------------|---------|
| `src\dashboard\app.py` | dashboard.app | Main Flask Application - Central app initialization and lifecycle management | app: Flask - Main Flask application instance |
| `src\main.py` | main | Server Entry Point - Starts the Flask application | (no direct exports, executed as script) |

## Other Modules

| File | Module | Description | Exports |
|------|--------|-------------|---------|
| `src\__init__.py` |  |  |  |
| `src\api\__init__.py` | api | API Module - Alternative app factory for API-only deployment | create_app(): Flask - Creates and configures Flask app, run_server(): None - Starts the API server, app: Flask - Application instance (created on import) |
| `src\api\models\responses.py` | api.models.responses | API Response Models - Generic response classes for API responses | BaseModel: Dataclass - Base class for all API models (frozen=True), BaseResponse: Dataclass - Base response for all API responses (frozen=True, slots=True, Generic) |
| `src\api\routes\__init__.py` | api.routes | API Route Registration - Central API route registration and authentication | blueprint: Blueprint - Flask blueprint for API routes, api: Api - Flask-RESTX API instance with Swagger UI |
| `src\api\routes\audio_routes.py` | api.routes.audio_routes | Audio API Routes - Flask-RESTX endpoints for audio processing | audio_ns: Namespace - Flask-RESTX namespace for audio endpoints, upload_parser: RequestParser - Parser for upload parameters |
| `src\api\routes\common_routes.py` | api.routes.common_routes | Common API Routes - Flask-RESTX endpoints for general operations | common_ns: Namespace - Flask-RESTX namespace for common endpoints |
| `src\api\routes\event_job_routes.py` | api.routes.event_job_routes | Event Job API Routes - Flask-RESTX endpoints for session job management | event_job_ns: Namespace - Flask-RESTX namespace for event job endpoints, DateTimeEncoder: Class - JSON encoder for datetime objects |
| `src\api\routes\event_routes.py` | api.routes.event_routes | Event API Routes - Flask-RESTX endpoints for event processing | event_ns: Namespace - Flask-RESTX namespace for event endpoints |
| `src\api\routes\imageocr_routes.py` | api.routes.imageocr_routes | ImageOCR API Routes - Flask-RESTX endpoints for image OCR processing | imageocr_ns: Namespace - Flask-RESTX namespace for ImageOCR endpoints, imageocr_upload_parser: RequestParser - Parser for upload parameters, imageocr_url_parser: RequestParser - Parser for URL parameters |
| `src\api\routes\pdf_routes.py` | api.routes.pdf_routes | PDF API Routes - Flask-RESTX endpoints for PDF processing | pdf_ns: Namespace - Flask-RESTX namespace for PDF endpoints |
| `src\api\routes\secretary_job_routes.py` | api.routes.secretary_job_routes | Secretary Job API Routes - Flask-RESTX endpoints for generic job management | secretary_ns: Namespace - Flask-RESTX namespace for secretary job endpoints, DateTimeEncoder: Class - JSON encoder for datetime objects, get_repo(): SecretaryJobRepository - Factory function for repository |
| `src\api\routes\session_routes.py` | api.routes.session_routes | Session API Routes - Flask-RESTX endpoints for session processing | session_ns: Namespace - Flask-RESTX namespace for session endpoints |
| `src\api\routes\story_routes.py` | api.routes.story_routes | Story API Routes - Flask-RESTX endpoints for story generation | story_ns: Namespace - Flask-RESTX namespace for story endpoints, CustomJSONEncoder: Class - JSON encoder for complex objects |
| `src\api\routes\track_routes.py` | api.routes.track_routes | Track API Routes - Flask-RESTX endpoints for track processing | track_ns: Namespace - Flask-RESTX namespace for track endpoints |
| `src\api\routes\transformer_routes.py` | api.routes.transformer_routes | Transformer API Routes - Flask-RESTX endpoints for text transformation | transformer_ns: Namespace - Flask-RESTX namespace for transformer endpoints |
| `src\api\routes\video_routes.py` | api.routes.video_routes | Video API Routes - Flask-RESTX endpoints for video and YouTube processing | video_ns: Namespace - Flask-RESTX namespace for video endpoints, video_upload_parser: RequestParser - Parser for video upload parameters, frames_form_parser: RequestParser - Parser for frame extraction parameters |
| `src\core\config.py` | core.config | Central Configuration Management - Loads and manages application configuration | Config: Class - Singleton configuration management, ApplicationConfig: TypedDict - Type definition for overall configuration, ServerConfig: TypedDict - Server configuration (+4 weitere) |
| `src\core\config_keys.py` | core.config_keys | API Key Management - Manages sensitive configuration values from environment variables | ConfigKeys: Class - Singleton for API key management |
| `src\core\config_utils.py` | core.config_utils | Configuration Utilities - Helper functions for configuration processing | replace_env_vars(): Union[Dict, List, str, Any] - Replaces environment variables in configuration, load_dotenv(): None - Loads .env file |
| `src\core\exceptions.py` | core.exceptions | Exception Definitions - Central error handling for processing service | BaseProcessingException: Class - Base exception with details, RateLimitExceeded: Class - Rate limit error, FileSizeLimitExceeded: Class - File size error (+4 weitere) |
| `src\core\models\__init__.py` |  |  |  |
| `src\core\models\audio.py` | core.models.audio | Audio Models - Dataclasses for audio processing and transcription | AudioProcessingError: Class - Audio-specific exception, TranscriptionSegment: Dataclass - Transcription segment, TranscriptionResult: Dataclass - Transcription result (+4 weitere) |
| `src\core\models\base.py` | core.models.base | Base Models - Fundamental dataclasses for API responses and processing info | BaseResponse: Dataclass - Base class for all API responses, ErrorInfo: Dataclass - Error information, RequestInfo: Dataclass - Request information (+2 weitere) |
| `src\core\models\enums.py` | core.models.enums | Enums and Type Aliases - Central enum definitions and type aliases | ProcessorType: Enum - Processor types, ProcessingStatus: Enum - Processing status, OutputFormat: Enum - Output formats (+3 weitere) |
| `src\core\models\event.py` | core.models.event | Event Models - Pydantic models for event processing and track aggregation | EventInput: Pydantic BaseModel - Event input data, EventOutput: Pydantic BaseModel - Event output data, EventData: Pydantic BaseModel - Event data container (+2 weitere) |
| `src\core\models\job_models.py` | core.models.job_models | Job Models - Dataclasses for asynchronous job processing and batch management | JobStatus: Enum - Job status values, AccessVisibility: Enum - Visibility values, AccessControl: Dataclass - Access control (frozen=True) (+4 weitere) |
| `src\core\models\llm.py` | core.models.llm | LLM Models - Dataclasses for Language Model interactions and tracking | LLModel: Dataclass - Basic LLM information, LLMRequest: Dataclass - Detailed request information, LLMInfo: Dataclass - Central tracking class for LLM usage |
| `src\core\models\metadata.py` | core.models.metadata | Metadata Models - Dataclasses for metadata extraction from various media types | ContentMetadata: Dataclass - Content metadata (frozen=True, slots=True), TechnicalMetadata: Dataclass - Technical metadata, MetadataData: Dataclass - Metadata container (+1 weitere) |
| `src\core\models\notion.py` | core.models.notion | Notion Models - Dataclasses for Notion integration | NotionBlock: Dataclass - Notion block (frozen=True), NotionPage: Dataclass - Notion page, NotionResponse: Dataclass - API response for Notion processing |
| `src\core\models\pdf.py` | core.models.pdf | PDF Models - Dataclasses for PDF processing and text extraction | PDFMetadata: Dataclass - PDF metadata (frozen=True for immutability), PDFProcessingResult: Class - Cacheable processing result, PDFResponse: Dataclass - API response for PDF processing |
| `src\core\models\protocols.py` | core.models.protocols | Protocol Definitions - Type protocols for structural subtyping | CacheableResult: Protocol - Protocol for cacheable results |
| `src\core\models\session.py` | core.models.session | Session Models - Dataclasses for session processing and media management | SessionInput: Dataclass - Session input data (frozen=True), SessionOutput: Dataclass - Session output data, SessionData: Dataclass - Session data container (+4 weitere) |
| `src\core\models\story.py` | core.models.story | Story Models - Dataclasses for story generation from sessions | StoryProcessorInput: Dataclass - Story input data (frozen=True), StoryProcessorOutput: Dataclass - Story output data, StoryData: Dataclass - Story data container (+2 weitere) |
| `src\core\models\track.py` | core.models.track | Track Models - Dataclasses for track processing and session aggregation | TrackInput: Dataclass - Track input data (frozen=True), TrackOutput: Dataclass - Track output data, TrackData: Dataclass - Track data container (+1 weitere) |
| `src\core\models\transformer.py` | core.models.transformer | Transformer Models - Dataclasses for text transformation and templates | CacheableResult: Protocol - Protocol for cacheable results, TemplateField: Dataclass - Template field definition, TemplateFields: Dataclass - Template fields collection (+5 weitere) |
| `src\core\models\translation.py` | core.models.translation | Translation Models - Dataclasses for translation management | Translation: Dataclass - Translation entry (slots=True) |
| `src\core\models\video.py` | core.models.video | Video Models - Dataclasses for video processing and audio extraction | VideoProcessingError: Class - Video-specific exception, VideoSource: Dataclass - Video source (URL/file), VideoMetadataProtocol: Protocol - Protocol for video metadata (+3 weitere) |
| `src\core\models\youtube.py` | core.models.youtube | YouTube Models - Dataclasses for YouTube video processing | YoutubeMetadataProtocol: Protocol - Protocol for YouTube metadata, YoutubeMetadata: Dataclass - YouTube metadata (frozen=True), YoutubeProcessingResult: Class - Cacheable processing result (+1 weitere) |
| `src\core\mongodb\__init__.py` |  |  |  |
| `src\core\mongodb\cache_setup.py` | core.mongodb.cache_setup | MongoDB Cache Setup - Setup script for MongoDB cache collections and indexes | setup_cache_collections(): Dict[str, List[str]] - Sets up all cache collections, setup_mongodb_caching(): None - Main setup function for MongoDB caching |
| `src\core\mongodb\connection.py` | core.mongodb.connection | MongoDB Connection - Singleton management of MongoDB connection | get_mongodb_client(): MongoClient - Singleton MongoDB client, get_mongodb_database(): Database - MongoDB database instance, setup_mongodb_connection(): None - Initializes MongoDB connection (+2 weitere) |
| `src\core\mongodb\repository.py` | core.mongodb.repository | Session Job Repository - MongoDB repository for session job management | SessionJobRepository: Class - Repository for session job management |
| `src\core\mongodb\secretary_repository.py` | core.mongodb.secretary_repository | Secretary Job Repository - MongoDB repository for generic secretary job management | SecretaryJobRepository: Class - Repository for generic secretary job management |
| `src\core\mongodb\secretary_worker_manager.py` | core.mongodb.secretary_worker_manager | Secretary Worker Manager - Generic background worker for secretary job processing | SecretaryWorkerManager: Class - Generic worker manager for secretary jobs |
| `src\core\mongodb\translation_repository.py` | core.mongodb.translation_repository | Translation Repository - MongoDB repository for translation management | TranslationRepository: Class - Repository for translation management |
| `src\core\mongodb\worker_manager.py` | core.mongodb.worker_manager | Session Worker Manager - Background worker for session job processing | SessionWorkerManager: Class - Worker manager for session jobs |
| `src\core\processing\__init__.py` |  |  |  |
| `src\core\processing\handlers\pdf_handler.py` | core.processing.handlers.pdf_handler | PDF Handler - Asynchronous PDF processing handler for Secretary Job Worker | handle_pdf_job(): Awaitable[None] - Async handler function for PDF jobs |
| `src\core\processing\handlers\session_handler.py` | core.processing.handlers.session_handler | Session Handler - Asynchronous session processing handler for Secretary Job Worker | handle_session_job(): Awaitable[None] - Async handler function for session jobs |
| `src\core\processing\handlers\transformer_handler.py` | core.processing.handlers.transformer_handler | Transformer Handler - Asynchronous template transformation handler for Secretary Job Worker | handle_transformer_template_job(): Awaitable[None] - Async handler function for transformer jobs |
| `src\core\processing\registry.py` | core.processing.registry | Processor Registry - Registry for generic job handlers | HandlerType: TypeAlias - Type alias for handler function signature, register(): None - Register a handler for a job_type, get_handler(): Optional[HandlerType] - Get handler for a job_type (+1 weitere) |
| `src\core\rate_limiting.py` | core.rate_limiting | Rate Limiting - Limits requests per IP address and file size | RateLimiter: Class - Rate limiting management |
| `src\core\resource_tracking.py` | core.resource_tracking | Resource Tracking - Calculates and tracks resource consumption for performance monitoring | ResourceUsage: Dataclass - Represents a resource usage, ResourceCalculator: Class - Calculates and tracks resource consumption |
| `src\core\services\__init__.py` |  |  |  |
| `src\core\services\translator_service.py` | core.services.translator_service | Translator Service - Service for text translation with caching | TranslatorService: Class - Service for text translation |
| `src\core\validation.py` | core.validation | Validation Utilities - Decorators and functions for dataclass validation | validate_field(): Callable - Decorator for field validation, validate_fields(): Callable - Decorator for multiple field validations, Various validation functions |
| `src\dashboard\routes\__init__.py` |  |  |  |
| `src\dashboard\routes\config_routes.py` | dashboard.routes.config_routes | Configuration Routes - Dashboard routes for configuration management | config: Blueprint - Flask blueprint for configuration routes |
| `src\dashboard\routes\docs_routes.py` | dashboard.routes.docs_routes | Documentation Routes - Dashboard routes for serving MkDocs-generated documentation | docs: Blueprint - Flask blueprint for documentation routes |
| `src\dashboard\routes\log_routes.py` | dashboard.routes.log_routes | Log Routes - Dashboard routes for log viewing and filtering | logs: Blueprint - Flask blueprint for log routes |
| `src\dashboard\routes\main_routes.py` | dashboard.routes.main_routes | Main Routes - Dashboard routes for main application views | main: Blueprint - Flask blueprint for main routes |
| `src\dashboard\routes\tests\__init__.py` |  |  |  |
| `src\dashboard\routes\tests\audio_test.py` |  |  |  |
| `src\dashboard\routes\tests\health_test.py` |  |  |  |
| `src\dashboard\routes\tests\transformer_test.py` |  |  |  |
| `src\dashboard\routes\tests\youtube_test.py` |  |  |  |
| `src\dashboard\utils.py` | dashboard.utils | Dashboard Utilities - Helper functions for dashboard application | get_system_info(): Dict[str, Any] - Get system information dictionary |
| `src\processors\__init__.py` |  |  |  |
| `src\processors\audio_processor.py` | processors.audio_processor | Audio Processor - Processing of audio files with transcription and transformation | AudioProcessor: Class - Audio processing processor, AudioSegmentProtocol: Protocol - Protocol for audio segments, WhisperTranscriberProtocol: Protocol - Protocol for Whisper transcriber |
| `src\processors\base_processor.py` | processors.base_processor | Base Processor - Common base class for all processors | BaseProcessor: Generic class - Base class for all processors |
| `src\processors\cacheable_processor.py` | processors.cacheable_processor | Cacheable Processor - Extended base class with MongoDB caching | CacheableProcessor: Generic class - Base class for cacheable processors, CacheableResult: Protocol - Protocol for cacheable results |
| `src\processors\event_processor.py` | processors.event_processor | Event Processor - Processing of events with track and session aggregation | EventProcessor: Class - Event processing processor, EventProcessingResult: Class - Event processing result, TrackInputDict: TypedDict - Track input structure (+2 weitere) |
| `src\processors\imageocr_processor.py` | processors.imageocr_processor | ImageOCR Processor - OCR processing of images with various methods | ImageOCRProcessor: Class - ImageOCR processing processor, ImageOCRMetadata: Dataclass - Image metadata |
| `src\processors\metadata_processor.py` | processors.metadata_processor | Metadata Processor - Metadata extraction from various media types | MetadataProcessor: Class - Metadata extraction processor, MetadataFeatures: Dataclass - Feature configuration, AudioSegmentProtocol: Protocol - Protocol for audio segments (+1 weitere) |
| `src\processors\pdf_processor.py` | processors.pdf_processor | PDF Processor - Processing of PDF files with text extraction and OCR | PDFProcessor: Class - PDF processing processor, PDFResponse: Dataclass - PDF processing response |
| `src\processors\session_processor.py` | processors.session_processor | Session Processor - Processing of session information and associated media | SessionProcessor: Class - Session processing processor, SessionProcessingResult: Class - Session processing result |
| `src\processors\story_processor.py` | processors.story_processor | Story Processor - Creation of thematic stories from sessions | StoryProcessor: Class - Story processing processor |
| `src\processors\track_processor.py` | processors.track_processor | Track Processor - Processing of event tracks with session aggregation | TrackProcessor: Class - Track processing processor, TrackProcessingResult: Class - Track processing result, safe_get(): T - Safe dictionary access with type conversion (+3 weitere) |
| `src\processors\transformer_processor.py` | processors.transformer_processor | Transformer Processor - Text transformation with LLM models | TransformerProcessor: Class - Text transformation processor |
| `src\processors\video_processor.py` | processors.video_processor | Video Processor - Processing of video files with audio extraction and transcription | VideoProcessor: Class - Video processing processor |
| `src\processors\youtube_processor.py` | processors.youtube_processor | YouTube Processor - Processing of YouTube videos with download and transcription | YoutubeProcessor: Class - YouTube processing processor, YoutubeDLInfo: TypedDict - YouTube-DL info structure, YoutubeDLOpts: TypedDict - YouTube-DL options structure (+1 weitere) |
| `src\scripts\init_cache.py` |  |  |  |
| `src\scripts\test_openwebui.py` |  |  |  |
| `src\tests\test_audio_processor_cache.py` |  |  |  |
| `src\tests\test_full_audio_cache.py` |  |  |  |
| `src\tests\test_lazy_import.py` |  |  |  |
| `src\tests\test_simple_audio_cache.py` |  |  |  |
| `src\tests\test_video_processor_cache.py` |  |  |  |
| `src\tools\process_single_event.py` |  |  |  |
| `src\tools\test_models.py` |  |  |  |
| `src\tools\test_mongodb.py` |  |  |  |
| `src\utils\__init__.py` |  |  |  |
| `src\utils\audio_utils.py` | utils.audio_utils | Audio Utilities - Utility class for audio file segmentation | AudioProcessor: Class - Utility class for audio segmentation |
| `src\utils\image2text_utils.py` | utils.image2text_utils | Image-to-Text Utilities - OpenAI Vision API integration for image text extraction | Image2TextService: Class - Service for image-to-text conversion with OpenAI Vision API |
| `src\utils\logger.py` | utils.logger | Logging System - Central logging system with structured logs and session tracking | ProcessingLogger: Class - Logger implementation for processors, LoggerService: Class - Singleton service for logger management, get_logger(): ProcessingLogger - Factory function for logger creation (+1 weitere) |
| `src\utils\openai_types.py` | utils.openai_types | OpenAI Types - Type definitions for OpenAI API interactions | WhisperSegment: Pydantic BaseModel - Whisper transcription segment, WhisperResponse: Pydantic BaseModel - Whisper API response, OpenAIDict: TypedDict - Base type for OpenAI API responses (+1 weitere) |
| `src\utils\openai_utils.py` | utils.openai_utils | OpenAI Utilities - Helper functions for OpenAI API integration | get_structured_gpt(): tuple[BaseModel, Dict, LLMRequest] - Structured GPT request |
| `src\utils\performance_tracker.py` | utils.performance_tracker | Performance Tracker - Centralized performance tracking for API calls and processors | PerformanceTracker: Class - Centralized performance tracking system, Various TypedDict classes for type safety (ClientInfo, ResourceInfo, etc.) |
| `src\utils\processor_cache.py` | utils.processor_cache | Processor Cache - Generic cache class for processor results | ProcessorCache: Generic class - Generic cache class for processor results, CacheableResult: Protocol - Protocol for cacheable result classes |
| `src\utils\transcription_utils.py` | utils.transcription_utils | Transcription Utilities - Whisper transcription and text transformation | WhisperTranscriber: Class - Whisper transcription class, AudioSegmentProtocol: Protocol - Protocol for audio segments, TemplateFieldDefinition: Dataclass - Template field definition |
| `src\utils\types\__init__.py` |  |  |  |
| `src\utils\types\pydub_types.py` |  |  |  |
| `src\utils\video_cache.py` | utils.video_cache | Video Cache - Cache management for video processing results | VideoCache: Class - Cache manager for video processing results, CacheMetadata: Dataclass - Metadata for cache entries |

