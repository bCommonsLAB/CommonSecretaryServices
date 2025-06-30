#!/usr/bin/env python3
"""
Session Archive Client - Beispiel-Script
Demonstriert die Nutzung der ZIP-Archiv-Funktionalität über die Job-API.
"""

import asyncio
import aiohttp
import json
import base64
import time
from pathlib import Path
from typing import Dict, Any, Optional


class SessionArchiveClient:
    """Client für die Session-Archive-API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def create_session_job(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """Erstellt einen neuen Session-Job"""
        
        job_data = {
            "job_type": "session_processing",
            "parameters": session_data
        }
        
        async with self.session.post(
            f"{self.base_url}/api/event-job/jobs",
            headers={"Content-Type": "application/json"},
            data=json.dumps(job_data)
        ) as response:
            result = await response.json()
            
            if response.status != 201:
                raise Exception(f"Job creation failed: {result}")
            
            return result
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Ruft den Status eines Jobs ab"""
        
        async with self.session.get(f"{self.base_url}/api/event-job/jobs/{job_id}") as response:
            result = await response.json()
            
            if response.status != 200:
                raise Exception(f"Failed to get job status: {result}")
            
            return result
    
    async def wait_for_job_completion(self, job_id: str, timeout: int = 300) -> Dict[str, Any]:
        """Wartet auf die Fertigstellung eines Jobs"""
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            result = await self.get_job_status(job_id)
            job = result.get("job", {})
            status = job.get("status")
            
            print(f"Job {job_id} Status: {status}")
            
            if status == "completed":
                return job
            elif status == "failed":
                error = job.get("error", {})
                raise Exception(f"Job failed: {error.get('message', 'Unknown error')}")
            
            # Warte 5 Sekunden vor nächster Abfrage
            await asyncio.sleep(5)
        
        raise TimeoutError(f"Job {job_id} did not complete within {timeout} seconds")
    
    async def download_archive(self, job_id: str, output_path: Path) -> bool:
        """Lädt das ZIP-Archiv eines Jobs herunter"""
        
        async with self.session.get(f"{self.base_url}/api/event-job/jobs/{job_id}/download-archive") as response:
            if response.status == 404:
                print(f"Job {job_id} not found")
                return False
            elif response.status == 400:
                error_data = await response.json()
                print(f"No archive available: {error_data.get('error', 'Unknown error')}")
                return False
            elif response.status != 200:
                error_data = await response.json()
                print(f"Download failed: {error_data}")
                return False
            
            # Stelle sicher, dass das Verzeichnis existiert
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Schreibe ZIP-Daten in Datei
            with open(output_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)
            
            print(f"Archive downloaded to: {output_path}")
            return True
    
    async def process_session_with_archive(
        self,
        session_data: Dict[str, Any],
        output_dir: Path = Path("./downloads")
    ) -> Optional[Path]:
        """Verarbeitet eine Session und lädt das ZIP-Archiv herunter"""
        
        # 1. Job erstellen
        print("Creating session job...")
        job_result = await self.create_session_job(session_data)
        job_id = job_result["job"]["job_id"]
        print(f"Job created: {job_id}")
        
        # 2. Auf Fertigstellung warten
        print("Waiting for job completion...")
        try:
            completed_job = await self.wait_for_job_completion(job_id)
            print("Job completed successfully!")
        except Exception as e:
            print(f"Job failed: {e}")
            return None
        
        # 3. Prüfe ob Archive verfügbar ist
        results = completed_job.get("results", {})
        archive_filename = results.get("archive_filename")
        
        if not archive_filename:
            print("No archive available for this job")
            return None
        
        # 4. Archive herunterladen
        print(f"Downloading archive: {archive_filename}")
        output_path = output_dir / archive_filename
        
        success = await self.download_archive(job_id, output_path)
        
        if success:
            print(f"Archive successfully downloaded to: {output_path}")
            return output_path
        else:
            print("Archive download failed")
            return None


async def main():
    """Beispiel-Nutzung des Archive-Clients"""
    
    # Session-Daten für FOSDEM 2025
    session_data = {
        "event": "FOSDEM 2025",
        "session": "Welcome to FOSDEM 2025",
        "url": "https://fosdem.org/2025/schedule/event/fosdem_welcome/",
        "filename": "welcome_fosdem_2025.md",
        "track": "Main Track",
        "attachments_url": "https://fosdem.org/2025/schedule/event/fosdem_welcome/attachments/welcome-slides.pdf",
        "source_language": "en",
        "target_language": "de",
        "template": "Session",
        "create_archive": True  # ZIP-Archiv aktivieren
    }
    
    # Client verwenden
    async with SessionArchiveClient() as client:
        try:
            archive_path = await client.process_session_with_archive(
                session_data=session_data,
                output_dir=Path("./session_archives")
            )
            
            if archive_path and archive_path.exists():
                print(f"\n✅ Success! Archive available at: {archive_path}")
                print(f"Archive size: {archive_path.stat().st_size} bytes")
                
                # Zeige ZIP-Inhalt an
                print("\nTo extract the archive:")
                print(f"  unzip {archive_path}")
                print(f"  cd {archive_path.stem}")
                print(f"  # Open the markdown file with your favorite editor")
                
            else:
                print("\n❌ Failed to download archive")
        
        except Exception as e:
            print(f"\n❌ Error: {e}")


def example_batch_processing():
    """Beispiel für Batch-Verarbeitung"""
    
    sessions = [
        {
            "event": "FOSDEM 2025",
            "session": "Welcome to FOSDEM 2025",
            "url": "https://fosdem.org/2025/schedule/event/fosdem_welcome/",
            "filename": "welcome.md",
            "track": "Main Track",
            "create_archive": True
        },
        {
            "event": "FOSDEM 2025", 
            "session": "State of LibreOffice",
            "url": "https://fosdem.org/2025/schedule/event/libreoffice_state/",
            "filename": "libreoffice_state.md",
            "track": "LibreOffice",
            "create_archive": True
        }
    ]
    
    print("Batch Processing Example:")
    print("========================")
    
    for i, session in enumerate(sessions, 1):
        print(f"{i}. {session['session']}")
        print(f"   URL: {session['url']}")
        print(f"   Archive: {'Yes' if session.get('create_archive') else 'No'}")
    
    print("\nTo process as batch:")
    print("1. Create batch via /api/event-job/batches")
    print("2. Monitor batch progress")
    print("3. Download archives for completed jobs")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        example_batch_processing()
    else:
        print("Session Archive Client Example")
        print("==============================")
        print("\nProcessing single session...")
        asyncio.run(main())
        print("\nFor batch processing example, run:")
        print(f"  python {sys.argv[0]} batch") 