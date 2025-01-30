"""
Implementierung des ProcessingSteps Features.
HINWEIS: Dies ist eine vorbereitete Implementierung für spätere Integration.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, ContextManager
from datetime import datetime, timezone
from enum import Enum
from contextlib import contextmanager

class ProcessingStatus(Enum):
    """Status eines Verarbeitungsschritts."""
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"

@dataclass
class ProcessingStep:
    """Ein einzelner Verarbeitungsschritt."""
    name: str
    status: ProcessingStatus = field(default=ProcessingStatus.PENDING)
    started_at: Optional[datetime] = field(default=None)
    completed_at: Optional[datetime] = field(default=None)
    duration_ms: Optional[float] = field(default=None)
    error: Optional[Dict[str, str]] = field(default=None)

class ProcessingStepTracker:
    """Basis-Implementierung für Step-Tracking Funktionalität."""
    
    def __init__(self):
        self.steps: List[ProcessingStep] = []
        self._current_step: Optional[ProcessingStep] = None

    async def start_step(self, name: str) -> ProcessingStep:
        """Startet einen neuen Verarbeitungsschritt."""
        step = ProcessingStep(
            name=name,
            status=ProcessingStatus.PENDING,
            started_at=datetime.now(timezone.utc)
        )
        self.steps.append(step)
        self._current_step = step
        return step

    async def end_step(self, 
                      status: ProcessingStatus = ProcessingStatus.SUCCESS, 
                      error: Optional[Dict[str, str]] = None) -> None:
        """Beendet den aktuellen Verarbeitungsschritt."""
        if self._current_step:
            step_end = datetime.now(timezone.utc)
            self._current_step.status = status
            self._current_step.completed_at = step_end
            self._current_step.duration_ms = (
                step_end - self._current_step.started_at
            ).total_seconds() * 1000 if self._current_step.started_at else 0
            if error:
                self._current_step.error = error

    @contextmanager
    async def step(self, name: str) -> ContextManager[ProcessingStep]:
        """Context Manager für Verarbeitungsschritte.
        
        Beispiel:
            async with tracker.step("extraction") as step:
                # Verarbeitung durchführen
                # Bei Erfolg wird der Step automatisch als SUCCESS markiert
                # Bei Exception wird er als ERROR markiert
        """
        try:
            step = await self.start_step(name)
            yield step
            await self.end_step(ProcessingStatus.SUCCESS)
        except Exception as e:
            await self.end_step(
                ProcessingStatus.ERROR,
                {'message': str(e), 'type': type(e).__name__}
            )
            raise

    def get_steps(self) -> List[ProcessingStep]:
        """Gibt alle aufgezeichneten Steps zurück."""
        return self.steps.copy()

    def clear_steps(self) -> None:
        """Löscht alle aufgezeichneten Steps."""
        self.steps.clear()
        self._current_step = None 