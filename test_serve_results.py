#!/usr/bin/env python
"""
Stellt die Ergebnisse der verarbeiteten Jobs über einen HTTP-Server bereit.
"""

import argparse
import logging
import sys
import os
from typing import Tuple, cast
import http.server
import socketserver
from urllib.parse import urlparse

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

class ResultsHandler(http.server.SimpleHTTPRequestHandler):
    """
    HTTP-Handler für die Bereitstellung der Ergebnisse.
    """
    
    def __init__(self, *args, **kwargs):
        """
        Initialisiert den Handler.
        """
        # Setze das Basisverzeichnis auf das Ausgabeverzeichnis
        self.directory = os.path.join(os.getcwd(), "output")
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """
        Behandelt GET-Anfragen.
        """
        # Parse den Pfad
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        # API-Endpunkte
        if path.startswith("/api/"):
            # Entferne "/api/" vom Pfad
            api_path = path[5:]
            
            # Dateien-Endpunkt
            if api_path.startswith("files/"):
                file_path = api_path[6:]
                self._serve_file(file_path)
            else:
                self.send_error(404, "API-Endpunkt nicht gefunden")
        else:
            # Standardverhalten für statische Dateien
            super().do_GET()
    
    def _serve_file(self, file_path: str) -> None:
        """
        Stellt eine Datei bereit.
        
        Args:
            file_path: Dateipfad relativ zum Ausgabeverzeichnis
        """
        # Bestimme den vollständigen Pfad
        full_path = os.path.join(self.directory, file_path)
        
        # Überprüfe, ob die Datei existiert
        if not os.path.isfile(full_path):
            self.send_error(404, f"Datei nicht gefunden: {file_path}")
            return
        
        # Bestimme den MIME-Typ
        if file_path.endswith(".md"):
            content_type = "text/markdown"
        elif file_path.endswith(".png"):
            content_type = "image/png"
        elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
            content_type = "image/jpeg"
        else:
            content_type = "application/octet-stream"
        
        # Sende die Datei
        try:
            with open(full_path, "rb") as f:
                content = f.read()
                
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            
            logger.info(f"Datei bereitgestellt: {file_path} ({content_type})")
        except Exception as e:
            logger.error(f"Fehler beim Bereitstellen der Datei {file_path}: {str(e)}")
            self.send_error(500, f"Interner Serverfehler: {str(e)}")

def start_server(port: int = 5001) -> None:
    """
    Startet den HTTP-Server.
    
    Args:
        port: Port, auf dem der Server lauschen soll
    """
    handler = ResultsHandler
    
    try:
        with socketserver.TCPServer(("", port), handler) as httpd:
            logger.info(f"Server gestartet auf Port {port}")
            logger.info(f"Ergebnisse verfügbar unter: http://localhost:{port}/api/files/")
            logger.info("Drücke Strg+C zum Beenden")
            httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server beendet")
    except Exception as e:
        logger.error(f"Fehler beim Starten des Servers: {str(e)}")
        sys.exit(1)

def main() -> None:
    """
    Hauptfunktion zum Starten des Servers.
    """
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description="Stellt die Ergebnisse der verarbeiteten Jobs über einen HTTP-Server bereit.")
    parser.add_argument("--port", type=int, default=5001, help="Port, auf dem der Server lauschen soll")
    args = parser.parse_args()
    
    # Server starten
    start_server(args.port)

if __name__ == "__main__":
    main() 