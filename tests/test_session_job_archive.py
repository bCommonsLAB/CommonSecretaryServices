"""
Test für die ZIP-Archiv-Integration in die MongoDB-Job-Pipeline.
Überprüft die korrekte Übertragung von Archive-Daten zwischen SessionProcessor und Job-System.
"""

import pytest
import asyncio
import base64
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from src.core.models.job_models import Job, JobResults, JobStatus, JobProgress
from src.core.models.session import SessionInput, SessionOutput, SessionData, SessionResponse
from src.core.mongodb.worker_manager import SessionWorkerManager
from src.core.mongodb.repository import SessionJobRepository
from src.core.resource_tracking import ResourceCalculator


class TestSessionJobArchive:
    """Test der ZIP-Archiv-Integration in die Job-Pipeline"""
    
    @pytest.fixture
    def mock_job_repo(self):
        """Mock für das Job-Repository"""
        repo = Mock(spec=SessionJobRepository)
        repo.update_job_status = Mock(return_value=True)
        repo.add_log_entry = Mock(return_value=True)
        return repo
    
    @pytest.fixture
    def worker_manager(self, mock_job_repo):
        """Worker-Manager mit Mock-Repository"""
        manager = SessionWorkerManager(job_repo=mock_job_repo)
        return manager
    
    @pytest.fixture
    def sample_job_with_archive_params(self):
        """Erstellt einen Job mit Archive-Parametern"""
        from src.core.models.job_models import JobParameters
        
        params = JobParameters()
        params.event = "FOSDEM 2025"
        params.session = "Welcome to FOSDEM"
        params.url = "https://fosdem.org/2025/schedule/event/welcome/"
        params.filename = "welcome_fosdem.md"
        params.track = "Main Track"
        params.attachments_url = "https://fosdem.org/2025/slides.pdf"
        params.create_archive = True  # ZIP-Archiv aktiviert
        
        job = Job(
            job_id="test-job-123",
            job_type="session_processing",
            status=JobStatus.PENDING,
            parameters=params
        )
        return job
    
    @pytest.fixture
    def mock_session_output_with_archive(self):
        """Mock für SessionOutput mit ZIP-Archiv-Daten"""
        # Erstelle Mock ZIP-Daten
        test_zip_content = b"PK\x03\x04test_zip_content"
        base64_zip = base64.b64encode(test_zip_content).decode('utf-8')
        
        session_input = SessionInput(
            event="FOSDEM 2025",
            session="Welcome to FOSDEM",
            url="https://fosdem.org/2025/schedule/event/welcome/",
            filename="welcome_fosdem.md",
            track="Main Track"
        )
        
        return SessionOutput(
            web_text="Test web content",
            video_transcript="Test video transcript",
            input_data=session_input,
            target_dir="/test/dir",
            markdown_file="/test/dir/welcome_fosdem.md",
            markdown_content="# Welcome to FOSDEM\n\nTest content",
            attachments=["image1.png", "image2.png"],
            structured_data={"topic": "Welcome", "relevance": "High"},
            archive_data=base64_zip,
            archive_filename="welcome_fosdem.zip",
            page_texts=["Page 1 text", "Page 2 text"]
        )
    
    @pytest.mark.asyncio
    async def test_worker_extracts_archive_data(self, worker_manager, sample_job_with_archive_params, mock_session_output_with_archive, mock_job_repo):
        """Test dass der Worker Archive-Daten korrekt extrahiert und speichert"""
        
        # Mock für den SessionProcessor
        with patch('src.processors.session_processor.SessionProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            
            # Mock für das process_session Ergebnis
            mock_response = Mock(spec=SessionResponse)
            mock_response.data = Mock()
            mock_response.data.output = mock_session_output_with_archive
            
            mock_processor.process_session.return_value = mock_response
            
            # Führe die Job-Verarbeitung aus
            await worker_manager._process_session(sample_job_with_archive_params)
            
            # Überprüfe, dass process_session mit create_archive=True aufgerufen wurde
            mock_processor.process_session.assert_called_once()
            call_args = mock_processor.process_session.call_args
            assert call_args.kwargs['create_archive'] is True
            
            # Überprüfe, dass update_job_status mit den korrekten Archive-Daten aufgerufen wurde
            mock_job_repo.update_job_status.assert_called_once()
            
            # Extrahiere die JobResults aus dem Aufruf
            call_args = mock_job_repo.update_job_status.call_args
            results = call_args.kwargs['results']
            
            assert isinstance(results, JobResults)
            assert results.archive_data == mock_session_output_with_archive.archive_data
            assert results.archive_filename == "welcome_fosdem.zip"
            assert results.structured_data == {"topic": "Welcome", "relevance": "High"}
            assert results.assets == ["image1.png", "image2.png"]
            assert results.page_texts == ["Page 1 text", "Page 2 text"]
    
    @pytest.mark.asyncio
    async def test_worker_handles_missing_archive_data(self, worker_manager, sample_job_with_archive_params, mock_job_repo):
        """Test dass der Worker korrekt mit fehlenden Archive-Daten umgeht"""
        
        # SessionOutput ohne Archive-Daten erstellen
        session_input = SessionInput(
            event="FOSDEM 2025",
            session="Test Session",
            url="https://example.com",
            filename="test.md",
            track="Test Track"
        )
        
        session_output_no_archive = SessionOutput(
            web_text="Test content",
            video_transcript="Test transcript",
            input_data=session_input,
            target_dir="/test/dir",
            markdown_file="/test/dir/test.md",
            markdown_content="# Test\n\nContent",
            # Keine Archive-Daten
            archive_data=None,
            archive_filename=None
        )
        
        with patch('src.processors.session_processor.SessionProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            
            mock_response = Mock(spec=SessionResponse)
            mock_response.data = Mock()
            mock_response.data.output = session_output_no_archive
            
            mock_processor.process_session.return_value = mock_response
            
            # Führe die Job-Verarbeitung aus
            await worker_manager._process_session(sample_job_with_archive_params)
            
            # Überprüfe, dass update_job_status aufgerufen wurde
            mock_job_repo.update_job_status.assert_called_once()
            
            # Extrahiere die JobResults
            call_args = mock_job_repo.update_job_status.call_args
            results = call_args.kwargs['results']
            
            # Archive-Felder sollten None sein
            assert results.archive_data is None
            assert results.archive_filename is None
    
    def test_job_results_serialization_with_archive(self):
        """Test dass JobResults mit Archive-Daten korrekt serialisiert werden"""
        
        test_zip_content = b"PK\x03\x04test_zip_content"
        base64_zip = base64.b64encode(test_zip_content).decode('utf-8')
        
        results = JobResults(
            markdown_content="# Test Content",
            archive_data=base64_zip,
            archive_filename="test_session.zip",
            structured_data={"topic": "Test"},
            assets=["image1.png"],
            page_texts=["Page 1"]
        )
        
        # Serialisierung testen
        results_dict = results.to_dict()
        
        assert results_dict['archive_data'] == base64_zip
        assert results_dict['archive_filename'] == "test_session.zip"
        assert results_dict['structured_data'] == {"topic": "Test"}
        assert results_dict['assets'] == ["image1.png"]
        assert results_dict['page_texts'] == ["Page 1"]
        
        # Deserialisierung testen
        restored_results = JobResults.from_dict(results_dict)
        
        assert restored_results.archive_data == base64_zip
        assert restored_results.archive_filename == "test_session.zip"
        assert restored_results.structured_data == {"topic": "Test"}
        assert restored_results.assets == ["image1.png"]
        assert restored_results.page_texts == ["Page 1"]
    
    def test_archive_data_base64_validation(self):
        """Test der Base64-Validierung für Archive-Daten"""
        
        # Gültige Base64-Daten
        valid_base64 = base64.b64encode(b"test content").decode('utf-8')
        
        try:
            decoded = base64.b64decode(valid_base64)
            assert decoded == b"test content"
        except Exception:
            pytest.fail("Gültige Base64-Daten sollten dekodierbar sein")
        
        # Ungültige Base64-Daten
        invalid_base64 = "invalid_base64_data!"
        
        with pytest.raises(Exception):
            base64.b64decode(invalid_base64, validate=True)
    
    @pytest.mark.asyncio
    async def test_create_archive_parameter_propagation(self, worker_manager, mock_job_repo):
        """Test dass der create_archive Parameter korrekt propagiert wird"""
        
        # Job mit create_archive=False
        from src.core.models.job_models import JobParameters
        
        params = JobParameters()
        params.event = "Test Event"
        params.session = "Test Session"
        params.url = "https://example.com"
        params.filename = "test.md"
        params.track = "Test Track"
        params.create_archive = False  # ZIP-Archiv deaktiviert
        
        job = Job(
            job_id="test-job-no-archive",
            job_type="session_processing",
            status=JobStatus.PENDING,
            parameters=params
        )
        
        with patch('src.processors.session_processor.SessionProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            
            # Mock Response ohne Archive-Daten
            mock_response = Mock(spec=SessionResponse)
            mock_response.data = Mock()
            mock_response.data.output = Mock()
            mock_response.data.output.archive_data = None
            mock_response.data.output.archive_filename = None
            
            mock_processor.process_session.return_value = mock_response
            
            # Führe die Job-Verarbeitung aus
            await worker_manager._process_session(job)
            
            # Überprüfe, dass process_session mit create_archive=False aufgerufen wurde
            mock_processor.process_session.assert_called_once()
            call_args = mock_processor.process_session.call_args
            assert call_args.kwargs['create_archive'] is False


if __name__ == "__main__":
    pytest.main([__file__]) 