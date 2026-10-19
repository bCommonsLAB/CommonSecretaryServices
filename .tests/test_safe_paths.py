"""
Tests fuer AP-03: Dateinamen und Pfade aus Requests verlassen nie ihren Basisordner.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import FileStorage

from src.utils.safe_paths import (
    ensure_within,
    is_safe_template_name,
    safe_path_component,
    safe_upload_name,
)


@pytest.mark.parametrize("filename, expected", [
    ("bericht.docx", "bericht.docx"),
    ("../../x.docx", "x.docx"),
    ("..\\..\\windows\\x.PPTX", "x.pptx"),
    ("/etc/passwd", "passwd"),
    ("Präsentation.PPTX", "Prasentation.pptx"),
    ("日本.docx", "upload.docx"),
    ("..", "upload"),
    (".docx", "docx"),
    ("", "upload"),
    (None, "upload"),
    ("a.d/o\\c..x", "c.x"),
    ("evil.ph$p", "evil.php"),
])
def test_safe_upload_name(filename: Any, expected: str) -> None:
    assert safe_upload_name(filename) == expected


def test_safe_upload_name_has_no_separator_or_leading_dot() -> None:
    for name in ["../.bashrc", ".htaccess", "....//....//x", "a/../../b.txt"]:
        result = safe_upload_name(name)
        assert "/" not in result and "\\" not in result
        assert not result.startswith(".")


@pytest.mark.parametrize("name, expected", [
    ("de", "de"),
    ("FOSDEM 2025", "FOSDEM 2025"),
    ("Südtirol Tag", "Südtirol Tag"),
    ("..", "unnamed"),
    (".", "unnamed"),
    ("../../etc", "_.._etc"),
    ("a\\b", "a_b"),
    ("x\x00y", "x_y"),
    ("", "unnamed"),
    (None, "unnamed"),
])
def test_safe_path_component(name: Any, expected: str) -> None:
    assert safe_path_component(name) == expected


@pytest.mark.parametrize("name, ok", [
    ("Session", True),
    ("Session_de", True),
    ("meine-vorlage v2", True),
    ("../secret", False),
    ("a/b", False),
    ("a\\b", False),
    (".hidden", False),
    ("", False),
    (None, False),
])
def test_is_safe_template_name(name: Any, ok: bool) -> None:
    assert is_safe_template_name(name) is ok


def test_ensure_within(tmp_path: Path) -> None:
    assert ensure_within(tmp_path, tmp_path / "a" / "b.txt") == (tmp_path / "a" / "b.txt").resolve()
    assert ensure_within(tmp_path, tmp_path) == tmp_path.resolve()
    with pytest.raises(ValueError):
        ensure_within(tmp_path / "base", tmp_path / "base" / ".." / "x")
    with pytest.raises(ValueError):
        ensure_within(tmp_path / "base", tmp_path / "base-sibling" / "x")


def test_ensure_within_rejects_symlink_escape(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (base / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        ensure_within(base, base / "link" / "x.txt")


def test_office_upload_stays_in_temp_dir(tmp_path: Path) -> None:
    from src.api.routes.office_routes import _save_upload_to_temp

    temp_dir = tmp_path / "job"
    upload = FileStorage(stream=io.BytesIO(b"data"), filename="../../x.docx")
    saved = Path(_save_upload_to_temp(upload, str(temp_dir)))
    assert saved == (temp_dir / "x.docx").resolve()
    assert saved.read_bytes() == b"data"
    assert not (tmp_path / "x.docx").exists()


def test_load_template_rejects_traversal(tmp_path: Path) -> None:
    from src.utils.template_utils import load_template

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "Session.md").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.md").write_text("geheim", encoding="utf-8")

    assert load_template(template_name="Session", templates_dir=str(templates)) == "ok"
    for name in ["../secret", "..\\secret", "/etc/passwd", ".hidden"]:
        with pytest.raises(ValueError):
            load_template(template_name=name, templates_dir=str(templates))


def _bare_processor(cls: Any, base_dir: Path) -> Any:
    processor = object.__new__(cls)
    processor.base_dir = base_dir
    processor.logger = MagicMock()
    return processor


def test_event_summary_name_and_language_stay_in_base_dir(tmp_path: Path) -> None:
    from src.processors.event_processor import EventProcessor

    base = tmp_path / "events"
    base.mkdir()
    processor = _bare_processor(EventProcessor, base)

    path = Path(asyncio.run(processor._save_event_summary("../../pwned", "x", "../../lang")))
    assert base.resolve() in path.resolve().parents
    assert not list(tmp_path.glob("pwned*"))

    normal = Path(asyncio.run(processor._save_event_summary("FOSDEM 2025", "y", "de")))
    assert normal.name == "FOSDEM 2025.md"
    assert normal.parent.name == "de"


def test_sanitize_filename_rejects_dot_names(tmp_path: Path) -> None:
    from src.processors.event_processor import EventProcessor

    processor = _bare_processor(EventProcessor, tmp_path)
    assert processor._sanitize_filename("..") == "unnamed"
    assert processor._sanitize_filename(".") == "unnamed"
    assert "/" not in processor._sanitize_filename("../../etc")


def test_session_assets_dir_rejects_traversal(tmp_path: Path) -> None:
    from src.core.exceptions import ProcessingError
    from src.processors.session_processor import SessionProcessor

    base = tmp_path / "sessions"
    base.mkdir()
    processor = _bare_processor(SessionProcessor, base)
    processor.pdf_processor = MagicMock()

    with pytest.raises(ProcessingError):
        asyncio.run(processor._process_attachments(
            attachments_url="https://example.org/a.pdf",
            session_data=MagicMock(),
            target_dir="../../pwned/assets/x",
        ))
    assert not (tmp_path / "pwned").exists()
    assert not (tmp_path.parent / "pwned").exists()
    processor.pdf_processor.process.assert_not_called()
