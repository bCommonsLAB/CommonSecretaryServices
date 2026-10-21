"""
Tests fuer die Wellen S und C1 des Plans „Playlist erschliessen" (src/api/routes/media_routes.py):

- /resolve liefert zusaetzlich einen Block `metadata` (Beschreibung, Datum als ISO,
  Kanal, Kapitel, Tags, bestes Vorschaubild, Seitenadresse); bestehende Felder bleiben.
- /playlist loest flach auf (extract_flat 'in_playlist', ohne noplaylist) und nennt
  private oder geloeschte Eintraege mit Grund, statt sie wegzulassen.
- noplaylist bleibt fuer /resolve und /download gesetzt.
- C1: Feld `cookies` je Aufruf als temporaere 0600-Datei an yt-dlp, Vorrang vor YTDLP_COOKIES_FILE,
  danach geloescht, nie in Antwort oder Log.

yt-dlp wird durch einen Fake ersetzt: kein Netz, keine Downloads.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from auth_test_support import TOKEN, clear_security_env, make_app
from src.api.routes import media_routes


class FakeYoutubeDL:
    """Ersatz fuer yt_dlp.YoutubeDL: merkt sich die Optionen und liefert vorbereitete Infos."""

    seen_opts: List[Dict[str, Any]] = []
    info: Any = None

    def __init__(self, opts: Dict[str, Any]) -> None:
        FakeYoutubeDL.seen_opts.append(dict(opts))

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> Any:
        assert download is False
        return FakeYoutubeDL.info


@pytest.fixture(autouse=True)
def _fake_ytdlp(monkeypatch: Any) -> None:
    FakeYoutubeDL.seen_opts = []
    FakeYoutubeDL.info = None
    monkeypatch.setattr(media_routes.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)


def _video_info(**extra: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "id": "abc123def45",
        "extractor": "youtube",
        "title": "start.klar. mit Gast",
        "duration": 3721,
        "ext": "m4a",
        "url": "https://cdn.example/audio.m4a",
        "protocol": "https",
        "http_headers": {"User-Agent": "x"},
        "vcodec": "none",
        "description": "Gast: Jemand\n\nThema: Etwas",
        "upload_date": "20150312",
        "uploader": "Markus Lobis",
        "channel": "start.klar.",
        "chapters": [{"start_time": 0.0, "end_time": 60.0, "title": "Begruessung"}],
        "tags": ["Bruneck", "Dialog"],
        "thumbnail": "https://i.example/default.jpg",
        "thumbnails": [
            {"url": "https://i.example/small.jpg", "width": 120, "height": 90},
            {"url": "https://i.example/maxres.jpg", "width": 1280, "height": 720},
            {"url": "https://i.example/unknown.jpg"},
        ],
        "webpage_url": "https://www.youtube.com/watch?v=abc123def45",
    }
    info.update(extra)
    return info


# --- /resolve: Metadaten-Block ---------------------------------------------------------------

def test_resolve_liefert_metadata_block_und_behaelt_alte_felder() -> None:
    FakeYoutubeDL.info = _video_info()
    data = media_routes.resolve_media_url("https://www.youtube.com/watch?v=abc123def45")
    assert data["url"] == "https://cdn.example/audio.m4a"
    assert data["ist_audio"] is True
    assert data["extractor"] == "youtube"
    meta = data["metadata"]
    assert meta["id"] == "abc123def45"
    assert meta["description"] == "Gast: Jemand\n\nThema: Etwas"
    assert meta["upload_date"] == "2015-03-12"
    assert meta["uploader"] == "Markus Lobis"
    assert meta["channel"] == "start.klar."
    assert meta["chapters"] == [{"title": "Begruessung", "start_time": 0.0, "end_time": 60.0}]
    assert meta["tags"] == ["Bruneck", "Dialog"]
    assert meta["thumbnail"] == "https://i.example/maxres.jpg"
    assert meta["webpage_url"] == "https://www.youtube.com/watch?v=abc123def45"


def test_resolve_metadata_fehlende_felder_bleiben_leer_nicht_geraten() -> None:
    FakeYoutubeDL.info = _video_info(
        upload_date=None, chapters=None, tags=None, thumbnails=None, thumbnail=None,
        description=None, channel=None, uploader=None, webpage_url=None,
    )
    meta = media_routes.resolve_media_url("https://example.org/video")["metadata"]
    assert meta["upload_date"] is None
    assert meta["chapters"] == []
    assert meta["tags"] == []
    assert meta["thumbnail"] is None
    assert meta["description"] is None
    assert meta["channel"] is None


def test_resolve_thumbnail_ohne_masse_nimmt_das_von_ytdlp_gewaehlte() -> None:
    FakeYoutubeDL.info = _video_info(
        thumbnails=[{"url": "https://i.example/a.jpg"}, {"url": "https://i.example/b.jpg"}],
        thumbnail="https://i.example/b.jpg",
    )
    assert media_routes.resolve_media_url("https://example.org/v")["metadata"]["thumbnail"] == "https://i.example/b.jpg"


@pytest.mark.parametrize("raw, erwartet", [
    ("20150312", "2015-03-12"),
    ("2015-03-12", None),
    ("", None),
    (None, None),
    (20150312, None),
])
def test_iso_date(raw: Any, erwartet: Optional[str]) -> None:
    assert media_routes._iso_date(raw) == erwartet


def test_resolve_und_download_behalten_noplaylist() -> None:
    FakeYoutubeDL.info = _video_info()
    media_routes.resolve_media_url("https://www.youtube.com/watch?v=abc123def45&list=PLxyz")
    assert FakeYoutubeDL.seen_opts[-1]["noplaylist"] is True
    assert "extract_flat" not in FakeYoutubeDL.seen_opts[-1]
    assert media_routes._ydl_opts({"outtmpl": "x"})["noplaylist"] is True


# --- /playlist: flache Liste ----------------------------------------------------------------

def _playlist_info() -> Dict[str, Any]:
    return {
        "_type": "playlist",
        "extractor": "youtube:tab",
        "id": "PLFE5FdV0STDOM-PpoSLTpWolTFL-OAuA7",
        "title": "start.klar. im UFO Bruneck",
        "uploader": "Markus Lobis",
        "channel": "Markus Lobis",
        "description": "Dialogreihe seit 2015",
        "webpage_url": "https://www.youtube.com/playlist?list=PLFE5FdV0STDOM-PpoSLTpWolTFL-OAuA7",
        "entries": [
            {"_type": "url", "id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Folge 1", "duration": 3600, "playlist_index": 1},
            {"_type": "url", "id": "v2", "url": "https://www.youtube.com/watch?v=v2", "title": "[Private video]", "duration": None, "playlist_index": 2},
            {"_type": "url", "id": "v3", "url": "https://www.youtube.com/watch?v=v3", "title": "[Deleted video]", "duration": None, "playlist_index": 3},
            {"_type": "url", "id": "v4", "url": "https://www.youtube.com/watch?v=v4", "title": "Folge 4", "duration": 1800, "availability": "needs_auth"},
            {"_type": "url", "id": "v5", "url": "https://www.youtube.com/watch?v=v5", "title": "Folge 5", "duration": 900, "live_status": "is_upcoming"},
        ],
    }


def test_playlist_opts_flach_ohne_noplaylist() -> None:
    FakeYoutubeDL.info = _playlist_info()
    media_routes.resolve_playlist("https://www.youtube.com/playlist?list=PLFE5FdV0STDOM-PpoSLTpWolTFL-OAuA7")
    opts = FakeYoutubeDL.seen_opts[-1]
    assert opts["extract_flat"] == "in_playlist"
    assert opts["noplaylist"] is False
    assert opts["skip_download"] is True


def test_playlist_liefert_kopf_und_eintraege_mit_grund() -> None:
    FakeYoutubeDL.info = _playlist_info()
    data = media_routes.resolve_playlist("https://www.youtube.com/playlist?list=PLFE5FdV0STDOM-PpoSLTpWolTFL-OAuA7")
    assert data["title"] == "start.klar. im UFO Bruneck"
    assert data["uploader"] == "Markus Lobis"
    assert data["description"] == "Dialogreihe seit 2015"
    assert data["anzahl"] == 5
    assert data["anzahl_verfuegbar"] == 1
    entries = data["entries"]
    assert [e["position"] for e in entries] == [1, 2, 3, 4, 5]
    assert entries[0] == {
        "position": 1, "id": "v1", "url": "https://www.youtube.com/watch?v=v1",
        "title": "Folge 1", "duration": 3600, "verfuegbar": True, "grund": None,
    }
    assert (entries[1]["verfuegbar"], entries[1]["grund"]) == (False, "privat")
    assert (entries[2]["verfuegbar"], entries[2]["grund"]) == (False, "geloescht")
    assert (entries[3]["verfuegbar"], entries[3]["grund"]) == (False, "Anmeldung noetig")
    assert entries[4]["verfuegbar"] is False and "angekuendigt" in entries[4]["grund"]


def test_playlist_position_aus_reihenfolge_wenn_index_fehlt() -> None:
    info = _playlist_info()
    for entry in info["entries"]:
        entry.pop("playlist_index", None)
    FakeYoutubeDL.info = info
    data = media_routes.resolve_playlist("https://example.org/playlist")
    assert [e["position"] for e in data["entries"]] == [1, 2, 3, 4, 5]


def test_playlist_leer_ist_fehler() -> None:
    info = _playlist_info()
    info["entries"] = []
    FakeYoutubeDL.info = info
    with pytest.raises(ValueError, match="leer"):
        media_routes.resolve_playlist("https://example.org/playlist")


def test_einzelnes_video_ist_keine_playlist() -> None:
    FakeYoutubeDL.info = _video_info()
    with pytest.raises(ValueError, match="keine Playlist"):
        media_routes.resolve_playlist("https://www.youtube.com/watch?v=abc123def45")


# --- Route -----------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch: Any) -> Any:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    c = make_app().test_client()
    c.environ_base["REMOTE_ADDR"] = "203.0.113.5"
    return c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_route_playlist_ohne_url_400(client: Any) -> None:
    resp = client.post("/api/media/playlist", json={}, headers=AUTH)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "MISSING_URL"


def test_route_playlist_keine_playlist_422(client: Any) -> None:
    FakeYoutubeDL.info = _video_info()
    resp = client.post("/api/media/playlist", json={"url": "https://www.youtube.com/watch?v=abc123def45"}, headers=AUTH)
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["error"]["code"] == "PLAYLIST_NOT_RESOLVABLE"
    assert "keine Playlist" in body["error"]["message"]


def test_route_playlist_unbekannte_seite_422(client: Any, monkeypatch: Any) -> None:
    def kaputt(self: Any, url: str, download: bool = False) -> Any:
        raise media_routes.yt_dlp.utils.DownloadError("Unsupported URL: " + url)

    monkeypatch.setattr(FakeYoutubeDL, "extract_info", kaputt)
    resp = client.post("/api/media/playlist", json={"url": "https://example.org/keine-playlist"}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "PLAYLIST_NOT_RESOLVABLE"


def test_route_playlist_erfolg(client: Any) -> None:
    FakeYoutubeDL.info = _playlist_info()
    resp = client.post("/api/media/playlist", json={"url": "https://www.youtube.com/playlist?list=PLFE5FdV0STDOM-PpoSLTpWolTFL-OAuA7"}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["anzahl"] == 5
    assert body["data"]["entries"][1]["grund"] == "privat"


def test_route_playlist_braucht_token(client: Any) -> None:
    assert client.post("/api/media/playlist", json={"url": "https://example.org/p"}).status_code == 401


def test_route_resolve_antwort_enthaelt_metadata(client: Any) -> None:
    FakeYoutubeDL.info = _video_info()
    resp = client.post("/api/media/resolve", json={"url": "https://www.youtube.com/watch?v=abc123def45"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["metadata"]["upload_date"] == "2015-03-12"


# --- Welle C1: Anmeldung je Aufruf (Feld `cookies`) -------------------------------------------
#
# Der Inhalt einer Netscape-cookies.txt kommt im Body mit, landet je Aufruf in einer temporaeren
# Datei mit Rechten 0600, geht als cookiefile an yt-dlp, hat Vorrang vor YTDLP_COOKIES_FILE und
# wird danach geloescht — auch wenn yt-dlp scheitert. Er taucht in keiner Antwort und keinem Log auf.

import os
import stat

COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tgeheim-abc\n"


class CookieSpy(FakeYoutubeDL):
    """Merkt sich beim Aufruf, ob die Cookie-Datei existiert, welche Rechte und welchen Inhalt sie hat."""

    gesehen: Dict[str, Any] = {}

    def __init__(self, opts: Dict[str, Any]) -> None:
        super().__init__(opts)
        self.opts = opts

    def extract_info(self, url: str, download: bool = False) -> Any:
        path = self.opts.get("cookiefile")
        if path and os.path.exists(path):
            CookieSpy.gesehen = {
                "path": path,
                "mode": stat.S_IMODE(os.stat(path).st_mode),
                "inhalt": open(path, encoding="utf-8").read(),
            }
        else:
            CookieSpy.gesehen = {"path": path}
        return super().extract_info(url, download)


@pytest.fixture
def spy(monkeypatch: Any) -> None:
    CookieSpy.gesehen = {}
    monkeypatch.setattr(media_routes.yt_dlp, "YoutubeDL", CookieSpy)


def test_cookies_landen_in_tempdatei_0600_und_verschwinden_danach(spy: Any) -> None:
    FakeYoutubeDL.info = _video_info()
    media_routes.resolve_media_url("https://www.youtube.com/watch?v=abc123def45", cookies=COOKIES)
    gesehen = CookieSpy.gesehen
    assert gesehen["inhalt"] == COOKIES
    assert gesehen["mode"] == 0o600
    assert os.path.basename(gesehen["path"]).startswith("ks-cookies-")
    assert not os.path.exists(gesehen["path"])


def test_cookies_haben_vorrang_vor_server_datei(spy: Any, monkeypatch: Any, tmp_path: Any) -> None:
    server = tmp_path / "server-cookies.txt"
    server.write_text("# server\n")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(server))
    FakeYoutubeDL.info = _playlist_info()
    media_routes.resolve_playlist("https://www.youtube.com/playlist?list=PL1", cookies=COOKIES)
    assert CookieSpy.gesehen["inhalt"] == COOKIES
    assert CookieSpy.gesehen["path"] != str(server)


def test_ohne_cookies_bleibt_server_datei(spy: Any, monkeypatch: Any, tmp_path: Any) -> None:
    server = tmp_path / "server-cookies.txt"
    server.write_text("# server\n")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(server))
    FakeYoutubeDL.info = _video_info()
    media_routes.resolve_media_url("https://example.org/v")
    assert CookieSpy.gesehen["path"] == str(server)


def test_ohne_cookies_und_ohne_server_datei_kein_cookiefile(spy: Any) -> None:
    FakeYoutubeDL.info = _video_info()
    media_routes.resolve_media_url("https://example.org/v")
    assert CookieSpy.gesehen["path"] is None


def test_cookie_datei_wird_auch_bei_ytdlp_fehler_geloescht(spy: Any, monkeypatch: Any) -> None:
    def kaputt(self: Any, url: str, download: bool = False) -> Any:
        path = self.opts["cookiefile"]
        assert os.path.exists(path)
        CookieSpy.gesehen = {"path": path}
        raise media_routes.yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(CookieSpy, "extract_info", kaputt)
    with pytest.raises(media_routes.yt_dlp.utils.DownloadError):
        media_routes.resolve_media_url("https://www.youtube.com/watch?v=abc123def45", cookies=COOKIES)
    assert not os.path.exists(CookieSpy.gesehen["path"])


def test_download_reicht_cookies_durch(spy: Any, monkeypatch: Any, tmp_path: Any) -> None:
    def laedt(self: Any, url: str, download: bool = False) -> Any:
        assert download is True
        CookieSpy.gesehen = {"path": self.opts["cookiefile"], "inhalt": open(self.opts["cookiefile"], encoding="utf-8").read()}
        (tmp_path / "medium.m4a").write_bytes(b"x")
        return _video_info()

    monkeypatch.setattr(CookieSpy, "extract_info", laedt)
    meta = media_routes.download_media("https://www.youtube.com/watch?v=abc123def45", str(tmp_path), cookies=COOKIES)
    assert meta["ext"] == "m4a"
    assert CookieSpy.gesehen["inhalt"] == COOKIES
    assert not os.path.exists(CookieSpy.gesehen["path"])


@pytest.mark.parametrize("payload, erwartet", [
    ({}, None),
    ({"cookies": None}, None),
    ({"cookies": COOKIES}, COOKIES),
])
def test_read_cookies_optional(payload: Dict[str, Any], erwartet: Optional[str]) -> None:
    assert media_routes._read_cookies(payload) == erwartet


@pytest.mark.parametrize("cookies", [123, ["a"], {"a": 1}, True, "", "   \n", "a\x00b", "x" * (media_routes.COOKIES_MAX_BYTES + 1)])
def test_read_cookies_unbrauchbar(cookies: Any) -> None:
    with pytest.raises(media_routes.InvalidCookies):
        media_routes._read_cookies({"cookies": cookies})


@pytest.mark.parametrize("pfad", ["/api/media/resolve", "/api/media/playlist", "/api/media/download"])
def test_route_cookies_falscher_typ_400(client: Any, pfad: str) -> None:
    resp = client.post(pfad, json={"url": "https://example.org/v", "cookies": 42}, headers=AUTH)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "INVALID_COOKIES"
    assert FakeYoutubeDL.seen_opts == []


def test_route_resolve_mit_cookies_nennt_inhalt_nirgends(client: Any, spy: Any) -> None:
    FakeYoutubeDL.info = _video_info()
    resp = client.post("/api/media/resolve", json={"url": "https://www.youtube.com/watch?v=abc123def45", "cookies": COOKIES}, headers=AUTH)
    assert resp.status_code == 200
    assert CookieSpy.gesehen["inhalt"] == COOKIES
    assert not os.path.exists(CookieSpy.gesehen["path"])
    assert "geheim-abc" not in resp.get_data(as_text=True)


def test_route_resolve_fehler_mit_cookies_nennt_inhalt_nirgends(client: Any, spy: Any, monkeypatch: Any) -> None:
    def kaputt(self: Any, url: str, download: bool = False) -> Any:
        raise media_routes.yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(CookieSpy, "extract_info", kaputt)
    resp = client.post("/api/media/resolve", json={"url": "https://www.youtube.com/watch?v=abc123def45", "cookies": COOKIES}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "MEDIA_NOT_RESOLVABLE"
    assert "geheim-abc" not in resp.get_data(as_text=True)
