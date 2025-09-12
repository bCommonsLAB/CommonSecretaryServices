"""
Kleines Testskript für OpenWebUI Chat Completions.

Ziele:
- Einfache Verbindung gegen einen OpenWebUI-Endpunkt testen
- Kurze Text-Transformation mit einem Gemma-Modell ausführen
- API-Key via CLI oder Umgebungsvariable nutzen

Hinweis zur Sicherheit: Der API-Key wird in Logs maskiert.

Referenz: https://docs.openwebui.com/getting-started/api-endpoints/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, TypedDict, cast, Union, Literal
import base64
import mimetypes
from textwrap import dedent

import requests
import hashlib

# Pfad zum Projektverzeichnis hinzufügen (robust wie in anderen Skripten)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from src.utils.logger import get_logger, ProcessingLogger  # noqa: E402


# ------------------------- Datamodelle (strikt typisiert) -------------------------


class ChatCompletionMessage(TypedDict, total=False):
    role: str
    content: Union[str, List[Dict[str, Any]]]


class ChatCompletionChoice(TypedDict, total=False):
    index: int
    message: ChatCompletionMessage
    finish_reason: str


class ChatCompletionResponse(TypedDict, total=False):
    id: str
    model: str
    choices: List[ChatCompletionChoice]


ContentPartText = TypedDict("ContentPartText", {"type": Literal["text"], "text": str})
ContentPartImageUrl = TypedDict(
    "ContentPartImageUrl",
    {"type": Literal["image_url"], "image_url": Dict[str, str]},
)
MessageContent = Union[str, List[Union[ContentPartText, ContentPartImageUrl]]]


@dataclass(slots=True, frozen=True)
class ChatMessage:
    """Nachrichtenmodell (unterstützt Text oder multi-modale Parts)."""

    role: str
    content: MessageContent

    def __post_init__(self) -> None:  # type: ignore[override]
        if self.role not in {"user", "assistant", "system"}:
            raise ValueError("role muss user/assistant/system sein")
        # content: str oder Liste von Parts mit 'type'
        if isinstance(self.content, list):
            if not all("type" in p for p in self.content):
                raise ValueError("content-Parts müssen Dicts mit 'type' sein")

    def to_dict(self) -> Dict[str, Any]:
        if isinstance(self.content, list):
            parts: List[Dict[str, Any]] = [cast(Dict[str, Any], p) for p in self.content]
            return {"role": self.role, "content": parts}
        return {"role": self.role, "content": self.content}


@dataclass(slots=True, frozen=True)
class ChatRequest:
    """Payload für POST /api/chat/completions.

    Nur die Felder, die wir hier benötigen, um es schlank zu halten.
    """

    model: str
    messages: List[ChatMessage]
    files: Optional[List[Mapping[str, str]]] = None

    def __post_init__(self) -> None:  # type: ignore[override]
        # Validierung: mindestens 1 Message
        if not self.messages:
            raise ValueError("messages darf nicht leer sein")
        if not self.model:
            raise ValueError("model ist ein Pflichtfeld (str)")

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.files:
            payload["files"] = list(self.files)
        return payload


@dataclass(slots=True, frozen=True)
class OpenWebUIConfig:
    """Konfiguration für den OpenWebUI-Client."""

    endpoint: str
    api_key: str

    def __post_init__(self) -> None:  # type: ignore[override]
        # Basic Validierungen, um offensichtliche Fehler früh zu erkennen.
        if not (self.endpoint.startswith("http://") or self.endpoint.startswith("https://")):
            raise ValueError("endpoint muss mit http:// oder https:// beginnen")
        if not self.api_key:
            raise ValueError("api_key ist ein Pflichtfeld (str)")


@dataclass(slots=True)
class OpenWebUIClient:
    """Minimaler Client für OpenWebUI Chat Completions API.

    Nutzt einen OpenAI-kompatiblen Endpunkt auf OpenWebUI:
    POST {endpoint}/api/chat/completions
    """

    config: OpenWebUIConfig
    logger: ProcessingLogger = field(init=False)

    def __post_init__(self) -> None:
        self.logger = get_logger(process_id="test-openwebui", processor_name="scripts")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def chat_completions(self, request: ChatRequest, timeout_seconds: int = 60) -> Dict[str, Any]:
        url = self.config.endpoint.rstrip("/") + "/api/chat/completions"

        masked_key = mask_api_key(self.config.api_key)
        self.logger.info(
            "Sende Chat Completion Request",
            url=url,
            endpoint=self.config.endpoint,
            model=request.model,
            api_key_masked=masked_key,
        )

        response = requests.post(url, headers=self._headers(), json=request.to_dict(), timeout=timeout_seconds)
        self.logger.debug("HTTP Response erhalten", status_code=response.status_code)

        response.raise_for_status()
        data: Dict[str, Any] = response.json()
        return data


# ------------------------------ Hilfsfunktionen ------------------------------


def mask_api_key(key: str) -> str:
    """Maskiert API-Key für sichere Logs."""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def build_transformation_prompt(text: str, instruction: str) -> str:
    """Erstellt eine kompakte Nutzer-Prompt für Texttransformationen."""
    return (
        "Du bist ein präziser Text-Transformer. Beachte strikt die Anweisung.\n"
        f"ANWEISUNG: {instruction}\n"
        "TEXT:"\
        f"\n{text}\n\n"
        "Antworte ausschließlich mit dem transformierten Text, ohne weitere Erklärungen."
    )


def image_file_to_data_url(path: str) -> str:
    """Liest eine Bilddatei und liefert eine data: URL (base64)."""
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _sha256_of_file(path: str) -> str:
    """Berechnet SHA256 des Dateiinhalts (hex)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_image_debug_info(path: str, data_url: str) -> Dict[str, Any]:
    """Erzeugt Debug-Infos zum Bild für Logging-Zwecke."""
    abs_path: str = os.path.abspath(path)
    size_bytes: int = os.path.getsize(path) if os.path.exists(path) else -1
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/png"
    b64_part: str = data_url.split(",", 1)[1] if "," in data_url else ""
    sha256_hex: str = _sha256_of_file(path)
    return {
        "abs_path": abs_path,
        "size_bytes": size_bytes,
        "mime": mime,
        "b64_length": len(b64_part),
        "sha256_hex": sha256_hex,
    }


# ----------------------------------- CLI -----------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Testet OpenWebUI Chat Completions (Gemma)")
    parser.add_argument("--endpoint", default=os.environ.get("OPENWEBUI_ENDPOINT", "https://ai.syswhite.dev/"), help="Basis-URL des OpenWebUI-Endpunkts")
    parser.add_argument("--api-key", default=os.environ.get("OPENWEBUI_API_KEY", ""), help="API-Key oder via env OPENWEBUI_API_KEY")
    parser.add_argument("--model", default=os.environ.get("OPENWEBUI_MODEL", "gemma3:12b"), help="LLM Modellname in OpenWebUI (z.B. gemma2)")
    parser.add_argument("--text", required=False, default="Dies ist ein kurzer Beispielsatz, der verbessert werden soll.", help="Eingabetext, der transformiert werden soll")
    parser.add_argument(
        "--instruction",
        default="Formuliere den Text klar, korrekt, kurz und beruflich neutral in Deutsch.",
        help="Transformation-Anweisung",
    )
    parser.add_argument("--image", required=False, help="Pfad zu einem Bild, das in Markdown übertragen werden soll")
    parser.add_argument("--b64-log-prefix-len", type=int, default=0, help="Optional: Anzahl Zeichen des Base64-Anfangs fürs Logging")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP Timeout in Sekunden")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    api_key: str = args.api_key or "sk-535b1765b2c24696ae928e7efb391443"
    if not api_key:
        # Fallback auf vom Nutzer bereitgestellten Schlüssel aus der Aufgabenstellung
        # WARNUNG: Hardcoding wird vermieden; hier nur als finaler Fallback.
        api_key = os.environ.get("LOCALBRAIN_API_KEY", "")
    if not api_key:
        print("Fehler: Kein API-Key übergeben. Setze --api-key oder env OPENWEBUI_API_KEY.")
        return 2

    try:
        config = OpenWebUIConfig(endpoint=str(args.endpoint), api_key=str(api_key))
        client = OpenWebUIClient(config=config)

        messages: List[ChatMessage] = []
        if args.image:
            # Multi-Modal: Text + Bild als data URL
            instruction = dedent("""\
Aufgabe:
Konvertiere die gesamte Seite aus einem Bild oder PDF 1:1 in Markdown-Text.

Regeln:

Lesereihenfolge: Analysiere zuerst die Spalten und setze den Text in korrekter Reihenfolge zusammen (von links nach rechts, oben nach unten).

Textübertragung: Übertrage den Text ohne Weglassen oder Hinzufügen – exakt wie ein OCR-Scanner. Keine inhaltlichen Änderungen, keine Zusammenfassungen.

Formatierung:

Überschriften → Markdown-Überschriften (#, ##, …).

Tabellen → Markdown-Tabellen, Spalten korrekt zuordnen.

Listen → mit - oder 1. darstellen.

Hervorhebungen (fett, kursiv) beibehalten, falls erkennbar.

Bilder und Grafiken:

Füge sie als Markdown-Image-Platzhalter ein: ![Beschreibung](imageX.png).

Erstelle zusätzlich eine kurze textuelle Beschreibung des Inhalts (z. B. „Diagramm mit Balken zu Umsatzzahlen 2023“).

Treue: Erfinde nichts, interpretiere nichts. Wenn etwas unleserlich ist, markiere es als [unleserlich].

Ziel: Ein perfektes, sauber formatiertes Markdown-Dokument, das die Seite so wiedergibt, wie sie im Original steht.Keine zusätzlichen anmerkungen.
            """).strip()
            data_url = image_file_to_data_url(str(args.image))
            # Debug-Infos zum Bild loggen (Pfad, Größe, MIME, SHA256, Base64-Länge)
            info = build_image_debug_info(str(args.image), data_url)
            self_logger = client.logger
            self_logger.info(
                "Bildinput vorbereitet",
                image_path=info["abs_path"],
                size_bytes=info["size_bytes"],
                mime=info["mime"],
                b64_length=info["b64_length"],
                sha256=info["sha256_hex"],
            )
            # Optional: kurzes Base64-Präfix ins Log (zur eindeutigen Zuordnung)
            try:
                prefix_len: int = int(getattr(args, "b64_log_prefix_len", 0))
            except Exception:
                prefix_len = 0
            if prefix_len > 0:
                b64_part: str = data_url.split(",", 1)[1] if "," in data_url else ""
                self_logger.debug("B64-Präfix", b64_prefix=b64_part[:prefix_len])
            parts: List[Union[ContentPartText, ContentPartImageUrl]] = [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
            messages.append(ChatMessage(role="user", content=parts))
        else:
            user_prompt = build_transformation_prompt(text=str(args.text), instruction=str(args.instruction))
            messages.append(ChatMessage(role="user", content=user_prompt))

        request = ChatRequest(model=str(args.model), messages=messages)

        result = client.chat_completions(request, timeout_seconds=int(args.timeout))

        # Extrahiere das wahrscheinlich relevante Feld (OpenAI-kompatibel: choices[0].message.content)
        transformed: Optional[str] = None
        try:
            resp = cast(ChatCompletionResponse, result)
            choices: List[ChatCompletionChoice] = resp.get("choices", [])
            if choices:
                message: ChatCompletionMessage = choices[0].get("message", {})
                content = message.get("content")
                if isinstance(content, str):
                    transformed = content
        except Exception:
            transformed = None

        print("\n--- API-Rohantwort (gekürzt) ---")
        print(json.dumps({k: v for k, v in result.items() if k in {"id", "model", "choices"}}, ensure_ascii=False)[:2000])

        print("\n--- Transformierter Text ---")
        print(transformed or "[Konnte Inhalt nicht extrahieren – vollständige Antwort siehe oben]")

        return 0
    except requests.HTTPError as http_err:
        print(f"HTTP-Fehler: {http_err}")
        try:
            if http_err.response is not None:
                print(http_err.response.text)
        except Exception:
            pass
        return 1
    except Exception as exc:
        print(f"Unerwarteter Fehler: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


