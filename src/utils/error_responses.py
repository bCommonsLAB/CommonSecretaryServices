"""
@fileoverview Fehlertexte fuer API-Antworten ohne Informationsabfluss (AP-05, Befund M3).

@description
API-Antworten duerfen weder Stacktraces noch rohe Texte unerwarteter Ausnahmen enthalten:
solche Texte verraten Dateipfade, interne Adressen, Datenbank-URIs oder Schluesselreste.

- Erwartete Fehler (eigene Ausnahmen aus `src.*`, `ValueError`, HTTP-Fehler von werkzeug)
  behalten ihre Meldung, weil Aufrufer sie zur Korrektur ihrer Anfrage brauchen. Die Meldung
  wird trotzdem von Pfaden und Geheimnissen bereinigt, da eigene Ausnahmen oft fremde Texte
  einbetten.
- Alle anderen Ausnahmen liefern eine allgemeine Meldung mit Referenz. Der volle Stacktrace
  steht unter derselben Referenz im Log.

@exports
- public_error_message: Meldung fuer die API-Antwort
- redact_sensitive: bereinigt einen Text von Pfaden und Geheimnissen
- is_public_error: ob die Meldung einer Ausnahme nach aussen darf
"""
from __future__ import annotations

import re
import traceback
import uuid
from typing import Optional

from werkzeug.exceptions import HTTPException

from src.utils.logger import get_logger

logger = get_logger(process_id="api-errors", processor_name="api-errors")

GENERIC_MESSAGE = "Interner Fehler"
_REF_ATTRIBUTE = "_public_error_ref"

# Zugangsdaten in Adressen: schema://benutzer:passwort@host
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
# Authorization-Header und Query-Parameter mit Geheimnissen
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}")
_SECRET_PARAM = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password|passwd|pwd|signature|sig)"
    r"(\s*[=:]\s*)(['\"]?)[^\s'\"&,;]{4,}"
)
# Bekannte Schluesselformate (OpenAI, OpenRouter, Mistral/Voyage-artig, GitHub)
_KEY_PREFIXES = re.compile(r"\b(sk|pk|pa|rk|ghp|gho|ghs|github_pat)[-_][A-Za-z0-9_\-*.]{8,}")
# Absolute Pfade: nur der Dateiname bleibt stehen. Der Lookbehind verhindert Treffer in URLs.
_UNIX_PATH = re.compile(
    r"(?<![\w/:.\-])/(?:app|home|root|tmp|var|usr|etc|opt|srv|mnt|data|proc|run|Users|private)"
    r"(?:/[^\s'\"<>:,;()\[\]]+)+"
)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\s'\"<>:,;()\[\]]+\\)*[^\s'\"<>:,;()\[\]]*")


def _basename(match: "re.Match[str]") -> str:
    path = match.group(0).rstrip("/\\")
    name = re.split(r"[/\\]", path)[-1]
    return f"<pfad>/{name}" if name else "<pfad>"


def redact_sensitive(text: str) -> str:
    """Entfernt Zugangsdaten, Schluessel und Verzeichnisse aus einem Fehlertext."""
    if not text:
        return text
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}<zugang>@", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} <token>", text)
    text = _SECRET_PARAM.sub(lambda m: f"{m.group(1)}{m.group(2)}<geheim>", text)
    text = _KEY_PREFIXES.sub("<schluessel>", text)
    text = _UNIX_PATH.sub(_basename, text)
    text = _WINDOWS_PATH.sub(_basename, text)
    return text


def is_public_error(error: BaseException) -> bool:
    """
    Erwartete Fehler, deren Meldung fuer den Aufrufer bestimmt ist: eigene Ausnahmen der
    Anwendung, Eingabefehler (ValueError) und HTTP-Fehler.
    """
    if isinstance(error, (ValueError, HTTPException)):
        return True
    module = type(error).__module__ or ""
    return module == "src" or module.startswith("src.")


def public_error_message(
    error: BaseException,
    expected: bool = False,
    process_id: Optional[str] = None,
) -> str:
    """
    Liefert den Text, der in einer API-Antwort stehen darf.

    Args:
        error: Die aufgetretene Ausnahme.
        expected: True, wenn der aufrufende except-Zweig einen fachlich erwarteten Fehler einer
            fremden Bibliothek behandelt (z. B. yt-dlp ``DownloadError``), dessen Meldung der
            Aufrufer braucht. Die Meldung wird dann bereinigt weitergegeben.
        process_id: Optionale Prozess-ID, die mit ins Log geschrieben wird.

    Returns:
        Bereinigte Meldung eines erwarteten Fehlers, sonst ``"Interner Fehler (Referenz: …)"``.
        Mehrere Aufrufe fuer dieselbe Ausnahme liefern dieselbe Referenz und loggen nur einmal.
    """
    if expected or is_public_error(error):
        if isinstance(error, HTTPException) and error.description:
            return redact_sensitive(str(error.description))
        return redact_sensitive(str(error))

    ref = getattr(error, _REF_ATTRIBUTE, None)
    if ref is None:
        ref = uuid.uuid4().hex[:12]
        try:
            setattr(error, _REF_ATTRIBUTE, ref)
        except Exception:
            pass
        stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        try:
            logger.error(
                f"Unerwarteter Fehler (Referenz: {ref})",
                error=error if isinstance(error, Exception) else None,
                error_ref=ref,
                error_type=type(error).__name__,
                request_process_id=process_id,
                stack_trace=stack,
            )
        except Exception:
            # Das Logging darf die Fehlerantwort nie verhindern.
            pass
    return f"{GENERIC_MESSAGE} (Referenz: {ref})"
