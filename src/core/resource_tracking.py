"""
@fileoverview Resource Tracking - Calculates and tracks resource consumption for performance monitoring

@description
Resource tracking system for Common Secretary Services. This file provides classes
and functions to calculate and track resource consumption.

The system tracks various resource types:
- Storage: Storage consumption (MB)
- Compute: Computation time (seconds)
- API Calls: Number of API calls
- Tokens: LLM token consumption

The ResourceCalculator class also calculates costs based on configured prices per unit.

@module core.resource_tracking

@exports
- ResourceUsage: Dataclass - Represents a resource usage
- ResourceCalculator: Class - Calculates and tracks resource consumption

@usedIn
- src.processors.base_processor: Tracks resource consumption for each processor
- src.processors.*: All processors use ResourceCalculator
- Performance monitoring: Uses ResourceCalculator for metrics

@dependencies
- Standard: dataclasses - Dataclass definitions
- Standard: typing - Type annotations
- Standard: datetime - Timestamps
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime

@dataclass
class ResourceUsage:
    type: str          # z.B. "storage", "compute"
    amount: float      # Menge der verwendeten Ressource
    unit: str          # z.B. "MB", "seconds"
    timestamp: Optional[datetime] = None
    cost: float = 0.0  # Kosten der Ressource

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class ResourceCalculator:
    """
    Berechnet und trackt Ressourcenverbrauch.
    Wird für Performance-Monitoring verwendet.
    """
    
    def __init__(self):
        """Initialisiert den ResourceCalculator."""
        self.total_tokens: int = 0
        self.total_api_calls: int = 0
        self.processing_times: Dict[str, float] = {}
        self.storage_cost_per_mb = 0.00001    # Beispielkosten pro MB
        self.compute_cost_per_second = 0.0001  # Beispielkosten pro Sekunde
        self.token_cost_per_1k = {
            "gpt-4": 0.03,      # $0.03 pro 1K Tokens
            "gpt-3.5": 0.002,   # $0.002 pro 1K Tokens
            "whisper-1": 0.006   # $0.006 pro 1K Tokens
        }
        self.resources: List[ResourceUsage] = []

    def calculate_storage_units(self, bytes_processed: int) -> float:
        """Berechnet Speichereinheiten in MB"""
        return bytes_processed / (1024 * 1024)  # Konvertierung zu MB

    def calculate_compute_units(self, seconds: float) -> float:
        """Berechnet Recheneinheiten basierend auf Zeit"""
        return seconds

    def calculate_total_units(self, resources: Optional[List[ResourceUsage]] = None) -> Dict[str, float]:
        """Berechnet Gesamteinheiten und Kosten für alle Ressourcen"""
        resources = resources or self.resources
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

    def track_usage(self, tokens: int, model: str, duration: float) -> None:
        """Trackt die Nutzung eines LLM-Modells."""
        # Compute-Zeit tracken
        self.resources.append(ResourceUsage(
            type="compute",
            amount=duration,
            unit="seconds"
        ))
        
        # Token-Nutzung tracken
        cost_per_1k = self.token_cost_per_1k.get(model, 0.01)  # Fallback auf $0.01/1K tokens
        token_cost = (tokens / 1000) * cost_per_1k
        self.resources.append(ResourceUsage(
            type="tokens",
            amount=tokens,
            unit="tokens",
            cost=token_cost
        ))

    def calculate_cost(self, tokens: int, model: str) -> float:
        """Berechnet die Kosten für eine bestimmte Token-Anzahl und ein Modell."""
        cost_per_1k = self.token_cost_per_1k.get(model, 0.01)  # Fallback auf $0.01/1K tokens
        return (tokens / 1000) * cost_per_1k

    def add_tokens(self, count: int, model: str) -> None:
        """
        Fügt Token-Verbrauch hinzu.
        
        Args:
            count: Anzahl der verbrauchten Token
            model: Name des verwendeten Modells
        """
        self.total_tokens += count
        
    def add_api_call(self, endpoint: str) -> None:
        """
        Trackt einen API-Aufruf.
        
        Args:
            endpoint: Name des aufgerufenen Endpoints
        """
        self.total_api_calls += 1
        
    def add_processing_time(self, step: str, time: float) -> None:
        """
        Fügt Verarbeitungszeit hinzu.
        
        Args:
            step: Name des Verarbeitungsschritts
            time: Benötigte Zeit in Sekunden
        """
        self.processing_times[step] = time
        
    def get_total_tokens(self) -> int:
        """Gibt die Gesamtzahl der verbrauchten Token zurück."""
        return self.total_tokens
        
    def get_total_api_calls(self) -> int:
        """Gibt die Gesamtzahl der API-Aufrufe zurück."""
        return self.total_api_calls
        
    def get_processing_times(self) -> Dict[str, float]:
        """Gibt die Verarbeitungszeiten zurück."""
        return self.processing_times.copy()
        
    def get_summary(self) -> Dict[str, Any]:
        """Erstellt eine Zusammenfassung der Ressourcennutzung."""
        return {
            "total_tokens": self.total_tokens,
            "total_api_calls": self.total_api_calls,
            "processing_times": self.processing_times.copy()
        } 