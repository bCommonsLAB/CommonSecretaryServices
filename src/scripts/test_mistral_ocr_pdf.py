import os
import json
from typing import Any, Dict, List, cast

import requests
from dotenv import load_dotenv


# Einfache, minimale OCR-Demo gegen Mistral OCR (PDF-Workflow)
# - API-Key via Umgebungsvariable: MISTRAL_API_KEY
# - Modell via Umgebungsvariable: MISTRAL_MODEL (optional, Default siehe unten)
# - PDF-Datei liegt im selben Verzeichnis wie dieses Skript und heißt "test1.pdf"


load_dotenv()
API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
MODEL: str = os.environ.get("MISTRAL_MODEL", "mistral-ocr-latest")


def _pdf_path() -> str:
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "test2.pdf")


def _upload_pdf_for_ocr(path: str) -> requests.Response:
    if not API_KEY:
        raise RuntimeError("Fehlender API-Key. Bitte env MISTRAL_API_KEY setzen.")
    url = "https://api.mistral.ai/v1/files"
    headers: Dict[str, str] = {"Authorization": f"Bearer {API_KEY}"}
    mime: str = "application/pdf"
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, mime)}
        data = {"purpose": "ocr"}
        return requests.post(url, headers=headers, files=files, data=data, timeout=120)


def chat_with_mistral() -> requests.Response:
    if not API_KEY:
        raise RuntimeError("Fehlender API-Key. Bitte env MISTRAL_API_KEY setzen.")

    # 1) PDF hochladen → file_id erhalten
    upload_resp = _upload_pdf_for_ocr(_pdf_path())
    try:
        upload_json_raw: Any = upload_resp.json()
    except Exception:
        upload_json_raw = {}
    upload_json: Dict[str, Any] = cast(Dict[str, Any], upload_json_raw) if isinstance(upload_json_raw, dict) else {}
    file_id: str = str(upload_json.get("id") or upload_json.get("file_id") or "")
    if not file_id:
        return upload_resp

    # 2) OCR-Endpoint mit File-Referenz
    url = "https://api.mistral.ai/v1/ocr"
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": MODEL,
        "document": {"type": "file", "file_id": file_id},
        # Beispiel-Extras bei Bedarf:
        # "pages": [0],
        # "include_image_base64": False,
    }
    return requests.post(url, headers=headers, json=payload, timeout=180)


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


