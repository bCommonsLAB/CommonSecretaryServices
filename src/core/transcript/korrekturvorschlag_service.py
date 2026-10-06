"""
@fileoverview Korrekturvorschlag-Dienst - ruft das Chat-Modell und prueft die Antwort

@description
Verbindet ``core.transcript.korrekturvorschlag`` (Prompt, Pruefung) mit dem in der Maske
fuer ``chat_completion`` zugeordneten Modell. Temperatur 0, keine Schema-Erzwingung:
das Schema steht im Prompt, die Pruefung danach ist streng.

@module core.transcript.korrekturvorschlag_service

@exports
- KorrekturvorschlagService: fuehrt einen Vorschlagslauf aus
- NO_MODEL_CONFIGURED, INVALID_LLM_RESPONSE: Fehlercodes fuer die Route
"""

from typing import Any, Dict, Optional, Sequence, Tuple

from ..exceptions import ProcessingError
from ..llm.config_manager import LLMConfigManager
from ..llm.use_cases import UseCase
from .korrekturvorschlag import Begleittext, Korrekturvorschlag, build_messages, parse_vorschlaege

NO_MODEL_CONFIGURED = "NO_MODEL_CONFIGURED"
INVALID_LLM_RESPONSE = "INVALID_LLM_RESPONSE"
# Grobe Obergrenze, damit ein versehentlich riesiger Upload nicht unbemerkt Geld kostet.
MAX_INPUT_CHARS = 600_000


class KorrekturvorschlagService:
    """Ein Vorschlagslauf: Prompt bauen, Modell fragen, Antwort pruefen."""

    def __init__(self, config_manager: Optional[LLMConfigManager] = None) -> None:
        self._config_manager = config_manager or LLMConfigManager()

    def _resolve(self) -> Tuple[Any, str]:
        self._config_manager.reload_config()
        provider = self._config_manager.get_provider_for_use_case(UseCase.CHAT_COMPLETION)
        model = self._config_manager.get_model_for_use_case(UseCase.CHAT_COMPLETION)
        if provider is None or not model:
            raise ProcessingError(
                "Fuer den Use-Case 'chat_completion' ist kein Modell zugeordnet.",
                details={"error_code": NO_MODEL_CONFIGURED},
            )
        return provider, model

    def vorschlagen(
        self, transkript: str, begleittexte: Sequence[Begleittext], zielsprache: str = "de"
    ) -> Tuple[Korrekturvorschlag, Dict[str, Any]]:
        """
        Liefert (Vorschlaege, Meta mit modell/tokens/dauer_ms).

        Raises:
            ProcessingError: ohne Modell, bei zu grosser Eingabe oder wenn die Antwort
                kein lesbares JSON ist
        """
        total = len(transkript) + sum(len(b.text) for b in begleittexte)
        if total > MAX_INPUT_CHARS:
            raise ProcessingError(
                f"Eingabe zu gross: {total} Zeichen, erlaubt sind {MAX_INPUT_CHARS}",
                details={"error_code": "INPUT_TOO_LARGE"},
            )
        provider, model = self._resolve()
        messages = build_messages(transkript, begleittexte, zielsprache)
        raw, llm_request = provider.chat_completion(messages=messages, model=model, temperature=0.0)
        try:
            vorschlag = parse_vorschlaege(raw, transkript, begleittexte)
        except ValueError as e:
            raise ProcessingError(
                f"Antwort des Modells '{model}' ist kein gueltiger Korrekturvorschlag: {e}",
                details={"error_code": INVALID_LLM_RESPONSE},
            ) from e
        meta = {
            "modell": model,
            "tokens": int(getattr(llm_request, "tokens", 0) or 0),
            "dauer_ms": float(getattr(llm_request, "duration", 0.0) or 0.0),
        }
        return vorschlag, meta
