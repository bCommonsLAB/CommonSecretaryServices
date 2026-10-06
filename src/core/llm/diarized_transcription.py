"""
@fileoverview Sprecher-Transkription - Modellwahl aus der Maske fuer den Sprecher-Weg

@description
Loest fuer ``POST /audio/process-diarized`` auf, welcher Provider und welches Modell
in der LLM-Konfigurationsmaske dem Use-Case ``diarized_transcription`` zugeordnet
sind. Der Code kennt keinen Modellnamen; die Maske entscheidet. Ist nichts
zugeordnet, gibt es einen klaren Fehler (NO_MODEL_CONFIGURED) statt eines Rueckfalls
auf das normale Transkriptionsmodell — das koennte keine Sprecher liefern.

@module core.llm.diarized_transcription

@exports
- DiarizedTranscriptionService: Loest Provider und Modell auf
- NO_MODEL_CONFIGURED, PROVIDER_UNSUPPORTED: Fehlercodes fuer die Route
"""

from typing import Any, Optional, Tuple

from ..exceptions import ProcessingError
from .config_manager import LLMConfigManager
from .use_cases import UseCase

NO_MODEL_CONFIGURED = "NO_MODEL_CONFIGURED"
PROVIDER_UNSUPPORTED = "PROVIDER_UNSUPPORTED"


class DiarizedTranscriptionService:
    """Modell und Provider fuer die Sprecher-Erkennung aus der Maske."""

    def __init__(self, config_manager: Optional[LLMConfigManager] = None) -> None:
        self._config_manager = config_manager or LLMConfigManager()

    def resolve(self) -> Tuple[Any, str]:
        """
        Liefert (Provider, Modellname) fuer ``diarized_transcription``.

        Raises:
            ProcessingError: ohne Zuordnung in der Maske (details.error_code
                NO_MODEL_CONFIGURED) oder wenn der Provider keine
                Sprecher-Erkennung kann (PROVIDER_UNSUPPORTED)
        """
        # Frisch laden, damit Aenderungen in der Maske ohne Neustart greifen.
        self._config_manager.reload_config()
        use_case_config = self._config_manager.get_use_case_config(UseCase.DIARIZED_TRANSCRIPTION)
        if not use_case_config or not use_case_config.model:
            raise ProcessingError(
                "Fuer den Use-Case 'diarized_transcription' ist kein Modell zugeordnet. "
                "Bitte in der LLM-Konfiguration (Maske) ein Modell mit Sprecher-Erkennung "
                "waehlen (Seed: gpt-4o-transcribe-diarize).",
                details={"error_code": NO_MODEL_CONFIGURED},
            )
        provider = self._config_manager.get_provider_for_use_case(UseCase.DIARIZED_TRANSCRIPTION)
        if provider is None:
            raise ProcessingError(
                "Fuer den Use-Case 'diarized_transcription' ist kein Provider verfuegbar.",
                details={"error_code": NO_MODEL_CONFIGURED},
            )
        if not callable(getattr(provider, "transcribe_diarized", None)):
            raise ProcessingError(
                f"Provider '{use_case_config.provider}' kann keine Sprecher-Erkennung "
                "(transcribe_diarized fehlt). Bitte in der Maske 'openai' zuordnen.",
                details={"error_code": PROVIDER_UNSUPPORTED},
            )
        return provider, use_case_config.model
