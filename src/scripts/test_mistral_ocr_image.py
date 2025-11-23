import os
import json
import base64
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv


# Einfache, minimale OCR-Demo gegen Mistral Chat Completions (Pixtral)
# - API-Key via Umgebungsvariable: MISTRAL_API_KEY
# - Modell via Umgebungsvariable: MISTRAL_MODEL (optional, Default siehe unten)
# - Bilddatei liegt im selben Verzeichnis wie dieses Skript und heißt "test1.jpeg"


load_dotenv()
API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
MODEL: str = os.environ.get("MISTRAL_MODEL", "mistral-ocr-latest")


def _image_path() -> str:
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "test2.jpeg")

def _to_data_url(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def chat_with_mistral() -> requests.Response:
    if not API_KEY:
        raise RuntimeError("Fehlender API-Key. Bitte env MISTRAL_API_KEY setzen.")

    url = "https://api.mistral.ai/v1/ocr"
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": MODEL,
        "document": {"type": "image_url", "image_url": _to_data_url(_image_path())},
    }
    return requests.post(url, headers=headers, json=payload, timeout=90)


def _print_response(resp: requests.Response) -> None:
    print("--- HTTP Status ---")
    print(resp.status_code)
    print("\n--- Headers ---")
    try:
        print(dict(resp.headers))
    except Exception:
        print("[Konnte Header nicht darstellen]")
    print("\n--- Body (raw) ---")
    try:
        text = resp.text
        print(text if len(text) <= 8000 else text[:8000] + "\n...[gekürzt]...")
    except Exception as exc:
        print(f"[Konnte Body nicht lesen: {exc}]")
    print("\n--- JSON (parsed, optional) ---")
    try:
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False)[:8000])
    except Exception as exc:
        print(f"[Keine valide JSON-Response: {exc}]")


def main() -> None:
    resp = chat_with_mistral()
    _print_response(resp)
    # Markdown extrahieren und ausgeben
    try:
        data: Dict[str, Any] = resp.json()
        pages_val: Any = data.get("pages")
        pages: List[Dict[str, Any]] = []
        if isinstance(pages_val, list):
            pages = [p for p in pages_val if isinstance(p, dict)]  # type: ignore[assignment]
        md_parts: List[str] = []
        for page in pages:
            md_val: Any = page.get("markdown")
            if isinstance(md_val, str):
                md_parts.append(md_val)
        if md_parts:
            markdown_out: str = "\n\n".join(md_parts)
            print("\n--- Markdown ---")
            print(markdown_out)
            # Optional: in Datei schreiben
            try:
                out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_output.md")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(markdown_out)
                print(f"\n[Gespeichert: {out_path}]")
            except Exception:
                pass
        else:
            print("\n[Kein Markdown-Feld gefunden]")
    except Exception as exc:
        print(f"\n[Konnte Markdown nicht extrahieren: {exc}]")


if __name__ == "__main__":
    main()


