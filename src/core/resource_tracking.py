from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime

@dataclass
class ResourceUsage:
    type: str          # z.B. "storage", "compute"
    amount: float      # Menge der verwendeten Ressource
    unit: str          # z.B. "MB", "seconds"
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class ResourceCalculator:
    def __init__(self):
        self.storage_cost_per_mb = 0.00001    # Beispielkosten pro MB
        self.compute_cost_per_second = 0.0001  # Beispielkosten pro Sekunde

    def calculate_storage_units(self, bytes_processed: int) -> float:
        """Berechnet Speichereinheiten in MB"""
        return bytes_processed / (1024 * 1024)  # Konvertierung zu MB

    def calculate_compute_units(self, seconds: float) -> float:
        """Berechnet Recheneinheiten basierend auf Zeit"""
        return seconds

    def calculate_total_units(self, resources: List[ResourceUsage]) -> Dict[str, float]:
        """Berechnet Gesamteinheiten und Kosten für alle Ressourcen"""
        total = {
            "storage_mb": 0.0,
            "compute_seconds": 0.0,
            "total_cost": 0.0
        }

        for resource in resources:
            if resource.type == "storage":
                total["storage_mb"] += resource.amount
                total["total_cost"] += resource.amount * self.storage_cost_per_mb
            elif resource.type == "compute":
                total["compute_seconds"] += resource.amount
                total["total_cost"] += resource.amount * self.compute_cost_per_second

        return total 