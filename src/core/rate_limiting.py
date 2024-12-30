from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List
import threading

class RateLimiter:
    def __init__(self, requests_per_hour: int, max_file_size: int):
        self.requests_per_hour = requests_per_hour
        self.max_file_size = max_file_size  # in Bytes
        self.requests: Dict[str, List[datetime]] = defaultdict(list)
        self.lock = threading.Lock()

    def is_allowed(self, ip: str) -> bool:
        """
        Überprüft, ob eine Anfrage von einer bestimmten IP erlaubt ist
        """
        with self.lock:
            now = datetime.now()
            hour_ago = now - timedelta(hours=1)
            
            # Alte Einträge entfernen
            self.requests[ip] = [t for t in self.requests[ip] if t > hour_ago]
            
            # Prüfen ob Limit erreicht
            if len(self.requests[ip]) < self.requests_per_hour:
                self.requests[ip].append(now)
                return True
            return False

    def check_file_size(self, size: int) -> bool:
        """
        Überprüft, ob die Dateigröße innerhalb des Limits liegt
        """
        return size <= self.max_file_size

    def get_remaining_requests(self, ip: str) -> int:
        """
        Gibt die Anzahl der verbleibenden Anfragen für eine IP zurück
        """
        with self.lock:
            now = datetime.now()
            hour_ago = now - timedelta(hours=1)
            current_requests = len([t for t in self.requests[ip] if t > hour_ago])
            return max(0, self.requests_per_hour - current_requests) 