"""
@fileoverview Safe paths - Dateinamen und Pfade aus fremden Eingaben sicher verwenden

@description
Arbeitspaket AP-03 aus docs/sicherheitsplan-umsetzung.md (Befunde H3, M6).
Client-Dateinamen, Template-Namen und Namen aus Request-Daten duerfen nie
Pfadtrenner oder ".." in einen Pfad tragen.

- safe_upload_name(): Upload-Dateiname ohne Verzeichnisanteile, lesbar, mit bereinigter Endung
- safe_path_component(): ein einzelner Pfadbestandteil (Ordner- oder Dateiname) aus Request-Daten
- is_safe_template_name(): erlaubte Template-Namen (keine Trenner, kein fuehrender Punkt)
- ensure_within(): bricht ab, wenn ein Zielpfad ausserhalb seines Basisordners liegt

@module utils.safe_paths
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Union

from werkzeug.utils import secure_filename

PathLike = Union[str, "os.PathLike[str]"]

_SUFFIX_RE = re.compile(r"[^a-z0-9]")
_TEMPLATE_NAME_RE = re.compile(r"^\w[\w\- .]*$", re.UNICODE)


def safe_upload_name(filename: Optional[str], default_stem: str = "upload", max_stem: int = 100) -> str:
    """
    Bereinigter Dateiname fuer einen Upload.

    Verzeichnisanteile ("../", "C:\\...") werden verworfen, der Name wird mit
    werkzeug.secure_filename auf ASCII-Zeichen ohne Trenner reduziert, die Endung
    auf Kleinbuchstaben und Ziffern. Bleibt kein Name uebrig, gilt ``default_stem``.

    Beispiele: "../../x.docx" -> "x.docx", "Präsentation.PPTX" -> "Prasentation.pptx",
    "日本.docx" -> "upload.docx", None -> "upload"
    """
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    stem, suffix = os.path.splitext(raw)
    if not stem and suffix:
        # ".docx" ohne Namen: Endung als Name gemeint, nicht als Suffix
        stem, suffix = suffix, ""
    safe_stem = secure_filename(stem).lstrip(".")[:max_stem] or default_stem
    safe_suffix = _SUFFIX_RE.sub("", suffix.lower())[:10]
    return f"{safe_stem}.{safe_suffix}" if safe_suffix else safe_stem


def safe_path_component(name: Optional[str], default: str = "unnamed") -> str:
    """
    Ein einzelner Pfadbestandteil aus Request-Daten (z. B. Eventname, Sprachcode).

    Ersetzt Pfadtrenner und Steuerzeichen, entfernt fuehrende Punkte (also auch "." und "..")
    und laesst Umlaute und Leerzeichen stehen, damit bestehende Namen lesbar bleiben.
    """
    value = re.sub(r"[/\\\x00-\x1f]", "_", name or "").strip().lstrip(".").strip()
    return value or default


def is_safe_template_name(name: Optional[str]) -> bool:
    """Template-Name ohne Pfadtrenner und ohne fuehrenden Punkt."""
    return bool(name) and bool(_TEMPLATE_NAME_RE.match(name or ""))


def ensure_within(base: PathLike, target: PathLike) -> Path:
    """
    Liefert ``target`` als absoluten Pfad, wenn er innerhalb von ``base`` liegt.

    Raises:
        ValueError: wenn ``target`` (nach Aufloesen von "..", Symlinks) ausserhalb liegt.
    """
    base_path = Path(base).resolve()
    target_path = Path(target).resolve()
    if target_path != base_path and base_path not in target_path.parents:
        raise ValueError(f"Pfad liegt ausserhalb von {base_path}: {target_path.name}")
    return target_path
