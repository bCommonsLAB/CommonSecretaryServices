"""
Unit-Tests für YouTube-spezifische yt-dlp-Optionen
(src/processors/ytdlp_youtube_opts.py).

Diese Tests setzen nur Umgebungsvariablen und prüfen Optionsschlüssel.
Es werden keine Cookie-Werte gelesen und kein Netzwerk genutzt.

Ausfuehren (aus dem Projektroot, in der venv):
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_ytdlp_youtube_opts.py -q
"""

from pathlib import Path
from typing import Any, Dict

from src.processors.ytdlp_youtube_opts import (
    apply_youtube_ytdlp_opts,
    build_youtube_ytdlp_extra_opts,
    classify_youtube_cookie_error,
    youtube_cookie_lock_message,
)


def test_default_opts_enable_node_runtime(monkeypatch: Any) -> None:
    """Ohne Cookie-Env bleibt die Node-Runtime aktiv."""
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.delenv("YTDLP_YOUTUBE_COOKIES_FILE", raising=False)
    opts = build_youtube_ytdlp_extra_opts()
    assert opts["js_runtimes"] == {"node": {}}
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts


def test_browser_cookies_are_used_when_no_youtube_file(monkeypatch: Any) -> None:
    """YTDLP_COOKIES_FROM_BROWSER wird als cookiesfrombrowser gesetzt."""
    monkeypatch.delenv("YTDLP_YOUTUBE_COOKIES_FILE", raising=False)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")
    opts = build_youtube_ytdlp_extra_opts()
    assert opts["cookiesfrombrowser"] == ("edge",)
    assert "cookiefile" not in opts


def test_youtube_cookie_file_takes_precedence(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Existierende YouTube-Cookie-Datei schlaegt Browser-Cookies."""
    cookie_file = tmp_path / "youtube.cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("YTDLP_YOUTUBE_COOKIES_FILE", str(cookie_file))
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")
    opts = build_youtube_ytdlp_extra_opts()
    assert opts["cookiefile"] == str(cookie_file)
    assert "cookiesfrombrowser" not in opts


def test_missing_youtube_cookie_file_falls_back_to_browser(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Nicht existierende Datei darf den Browser-Fallback nicht blockieren."""
    missing = tmp_path / "missing.cookies.txt"
    monkeypatch.setenv("YTDLP_YOUTUBE_COOKIES_FILE", str(missing))
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")
    opts = build_youtube_ytdlp_extra_opts()
    assert "cookiefile" not in opts
    assert opts["cookiesfrombrowser"] == ("edge",)


def test_apply_merges_into_existing_opts(monkeypatch: Any) -> None:
    """apply_youtube_ytdlp_opts ergaenzt ein bestehendes Dict."""
    monkeypatch.delenv("YTDLP_YOUTUBE_COOKIES_FILE", raising=False)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")
    base: Dict[str, Any] = {"quiet": True, "format": "bestaudio/best"}
    apply_youtube_ytdlp_opts(base)
    assert base["quiet"] is True
    assert base["cookiesfrombrowser"] == ("edge",)
    assert base["js_runtimes"] == {"node": {}}


def test_cookiesfrombrowser_is_tuple_not_string(monkeypatch: Any) -> None:
    """String "edge" wuerde yt-dlp als Browser "e" lesen. Deshalb Tuple."""
    monkeypatch.delenv("YTDLP_YOUTUBE_COOKIES_FILE", raising=False)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "edge")
    spec = build_youtube_ytdlp_extra_opts()["cookiesfrombrowser"]
    assert isinstance(spec, tuple)
    assert spec[0] == "edge"
    assert spec != "edge"


def test_cookie_lock_message_detects_ytdlp_error() -> None:
    """Die gesperrte Chromium-Cookie-DB muss eine klare Meldung liefern."""
    err = RuntimeError(
        "Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271"
    )
    failure = classify_youtube_cookie_error(err)
    assert failure is not None
    assert failure.code == "COOKIE_DB_LOCKED"
    assert "gesperrt" in failure.message
    assert youtube_cookie_lock_message(RuntimeError("HTTP Error 403")) is None


def test_dpapi_error_points_to_firefox_or_cookie_file() -> None:
    """Chromium-DPAPI ist unter Windows eine Sackgasse."""
    err = RuntimeError(
        "Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927"
    )
    failure = classify_youtube_cookie_error(err)
    assert failure is not None
    assert failure.code == "COOKIE_DPAPI"
    assert "Firefox" in failure.message
    assert "YTDLP_YOUTUBE_COOKIES_FILE" in failure.message
