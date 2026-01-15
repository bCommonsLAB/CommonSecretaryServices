from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Iterator


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_dir(path: Path) -> None:
    """Erstellt ein Verzeichnis (inkl. Parents), falls es nicht existiert."""
    path.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """Macht Dateinamen stabil und filesystem-sicher."""
    n = name.strip()
    if not n:
        return "file"
    n = n.replace("\\", "_").replace("/", "_")
    n = _FILENAME_SAFE_RE.sub("_", n)
    return n[:180] if len(n) > 180 else n


def iter_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                return
            yield b


def md5_file(path: Path) -> str:
    """MD5 über Dateiinhalt (für Cache-Key)."""
    h = hashlib.md5()
    for chunk in iter_file_chunks(path):
        h.update(chunk)
    return h.hexdigest()


def guess_soffice_path() -> str:
    """Ermittelt eine sinnvolle `soffice`-Binary-Referenz.

    Hinweis: Für Windows ist das heute im PDFProcessor hart verdrahtet.
    Wir übernehmen das für Pipeline B, damit Verhalten konsistent bleibt.
    """
    if os.name == "nt":
        return r"C:\Program Files\LibreOffice\program\soffice.exe"
    return "soffice"






