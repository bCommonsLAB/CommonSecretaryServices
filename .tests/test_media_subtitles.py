"""
Tests fuer POST /api/media/subtitles (src/api/routes/media_subtitle_routes.py, src/processors/subtitle_tracks.py):

- Spurwahl: von Hand gepflegte Spur der gewuenschten Sprache gewinnt, sonst die automatische Spur in der
  Originalsprache (`<sprache>-orig`); uebersetzte Spuren (`tlang`) und der Live-Chat zaehlen nie.
- Ohne brauchbare Spur ein Fehler mit Grund, kein stiller Rueckfall.
- Formate json3, vtt (rollende Wiederholungen fallen weg) und srt.
- Absaetze mit Zeitmarken, neu je Kapitelbeginn und rund je Minute; Abdeckung mit groesster Luecke.
- Route: Optionen an yt-dlp, Cookies wie bei den anderen Medien-Routen, Fehlercodes.

yt-dlp wird durch einen Fake ersetzt: kein Netz. Die Untertiteldateien unter fixtures/untertitel sind
nach dem Aufbau der Formate von Hand gebaut, nicht von YouTube aufgezeichnet.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from auth_test_support import TOKEN, clear_security_env, make_app
from src.api.routes import media_routes, media_subtitle_routes
from src.processors import subtitle_tracks as st

FIXTURES = Path(__file__).parent / "fixtures" / "untertitel"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tgeheim-abc\n"
URL = "https://www.youtube.com/watch?v=hCEHADgvf8A"


def _lies(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _spur(sprache: str, *, tlang: bool = False, formate: tuple = ("json3", "srv1", "vtt")) -> List[Dict[str, Any]]:
    query = f"&tlang={sprache}" if tlang else ""
    return [{"ext": ext, "url": f"https://www.youtube.com/api/timedtext?v=x&lang=en&fmt={ext}{query}", "name": sprache} for ext in formate]


def _info(**extra: Any) -> Dict[str, Any]:
    """Frueherer Livestream wie das Side Event: nur automatische Spuren, Englisch ist das Original."""
    info: Dict[str, Any] = {
        "id": "hCEHADgvf8A", "extractor": "youtube", "title": "Beyond the Numbers", "duration": 310,
        "language": "en-US", "live_status": "was_live", "webpage_url": URL, "upload_date": "20261110",
        "chapters": [{"title": "Opening remarks", "start_time": 0.0, "end_time": 60.0}, {"title": "Panel", "start_time": 60.0, "end_time": 310.0}],
        "subtitles": {"live_chat": [{"ext": "json", "url": "https://www.youtube.com/live_chat_replay?x=1", "protocol": "youtube_live_chat_replay"}]},
        "automatic_captions": {
            "en-orig": _spur("en"), "en": _spur("en"),
            "de": _spur("de", tlang=True), "fr": _spur("fr", tlang=True),
        },
    }
    info.update(extra)
    return info


class FakeYoutubeDL:
    """Ersatz fuer yt_dlp.YoutubeDL: liefert vorbereitete Infos und schreibt beim Laden einer Spur eine Fixture."""

    seen_opts: List[Dict[str, Any]] = []
    geladen: List[Dict[str, Any]] = []
    info: Any = None
    datei: Dict[str, str] = {}

    def __init__(self, opts: Dict[str, Any]) -> None:
        FakeYoutubeDL.seen_opts.append(dict(opts))

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> Any:
        assert download is False
        return FakeYoutubeDL.info

    def dl(self, name: str, info: Dict[str, Any], subtitle: bool = False, test: bool = False) -> Any:
        assert subtitle is True
        FakeYoutubeDL.geladen.append(dict(info))
        inhalt = FakeYoutubeDL.datei.get(info["ext"])
        if inhalt is not None:
            Path(name).write_text(inhalt, encoding="utf-8")
        return True, True


@pytest.fixture(autouse=True)
def _fake_ytdlp(monkeypatch: Any) -> None:
    FakeYoutubeDL.seen_opts = []
    FakeYoutubeDL.geladen = []
    FakeYoutubeDL.info = None
    FakeYoutubeDL.datei = {"json3": _lies("asr_en.json3"), "vtt": _lies("asr_en.vtt"), "srt": _lies("manuell_de.srt")}
    monkeypatch.setattr(media_routes.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)


@pytest.fixture
def client(monkeypatch: Any) -> Any:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    return make_app().test_client()


# --- Spurwahl ---------------------------------------------------------------------------------

def test_automatische_spur_der_originalsprache_wenn_keine_von_hand() -> None:
    track = st.choose_track(_info())
    assert (track.key, track.sprache, track.art) == ("en-orig", "en", "automatisch")
    assert track.entry["ext"] == "json3"
    assert track.verfuegbar == {"manuell": [], "automatisch_original": ["en"], "automatisch_uebersetzt": 2, "originalsprache": "en"}


def test_von_hand_gepflegte_spur_gewinnt() -> None:
    info = _info(subtitles={"en-US": _spur("en-US", formate=("vtt",)), "de": _spur("de", formate=("vtt",))})
    track = st.choose_track(info)
    assert (track.key, track.sprache, track.art, track.entry["ext"]) == ("en-US", "en", "manuell", "vtt")
    assert st.choose_track(info, "de").key == "de"


def test_uebersetzte_spur_ist_nie_das_transkript() -> None:
    """Gewuenscht ist Deutsch, es gibt nur die maschinelle Uebersetzung: die englische Originalspur wird genommen."""
    track = st.choose_track(_info(), "de")
    assert (track.key, track.sprache, track.art) == ("en-orig", "en", "automatisch")


def test_ohne_orig_kennung_zaehlt_die_spur_ohne_tlang() -> None:
    info = _info(automatic_captions={"it": _spur("it"), "en": _spur("en", tlang=True)}, language=None)
    track = st.choose_track(info)
    assert (track.key, track.sprache) == ("it", "it")


@pytest.mark.parametrize("extra, sprache, grund", [
    ({"subtitles": {}, "automatic_captions": {}}, None, st.KEINE_UNTERTITEL),
    ({"automatic_captions": {}}, None, st.KEINE_UNTERTITEL),  # nur der Live-Chat
    ({"automatic_captions": {"de": _spur("de", tlang=True)}}, None, st.NUR_UEBERSETZTE_SPUREN),
    ({"subtitles": {"fr": _spur("fr")}, "automatic_captions": {}}, "de", st.KEINE_UNTERTITEL),
    ({"subtitles": {"fr": _spur("fr"), "it": _spur("it")}, "automatic_captions": {}, "language": None}, None, st.SPRACHE_NICHT_EINDEUTIG),
    ({"automatic_captions": {"en-orig": _spur("en", formate=("srv1", "ttml"))}}, None, st.FORMAT_NICHT_LESBAR),
    ({"live_status": "is_live"}, None, st.VIDEO_LAEUFT_NOCH),
])
def test_keine_brauchbare_spur_nennt_den_grund(extra: Dict[str, Any], sprache: Any, grund: str) -> None:
    with pytest.raises(st.NoSubtitleTrack) as fehler:
        st.choose_track(_info(**extra), sprache)
    assert fehler.value.grund == grund


def test_eine_gepflegte_spur_ohne_bekannte_sprache_des_videos() -> None:
    info = _info(subtitles={"it": _spur("it", formate=("vtt",))}, automatic_captions={}, language=None)
    assert st.choose_track(info).key == "it"


# --- Formate ----------------------------------------------------------------------------------

def test_json3_zeilen_ohne_fenster_und_umbrueche() -> None:
    cues = st.parse_cues(_lies("asr_en.json3"), "json3")
    assert [c.text for c in cues] == [
        "good morning everyone", "welcome to this side event.", "[Music]",
        "concessional finance and sukuk", "the NCQG is 300 billion", "thank you",
    ]
    assert (cues[0].start, cues[0].end) == (1.2, 5.36)
    assert cues[-1].start == 300.5


def test_vtt_rollende_wiederholungen_fallen_weg() -> None:
    cues = st.parse_cues(_lies("asr_en.vtt"), "vtt")
    assert [c.text for c in cues] == ["good morning everyone", "welcome to this side event.", "concessional finance & sukuk"]
    assert [c.start for c in cues] == [1.2, 3.2, 65.0]


def test_srt_mit_komma_und_auszeichnung() -> None:
    cues = st.parse_cues(_lies("manuell_de.srt"), "srt")
    assert [c.text for c in cues] == ["Guten Morgen und willkommen.", "Heute geht es um Klimafinanzierung", "und Anpassung."]
    assert (cues[0].start, cues[1].start, cues[1].end) == (0.5, 4.2, 9.0)


def test_fremdes_format_und_kaputtes_json_sind_fehler() -> None:
    with pytest.raises(ValueError, match="nicht lesbar"):
        st.parse_cues("<tt/>", "ttml")
    with pytest.raises(ValueError, match="kein gueltiges JSON"):
        st.parse_cues("<html>", "json3")
    with pytest.raises(ValueError, match="events"):
        st.parse_cues("{}", "json3")


# --- Aufbereitung -----------------------------------------------------------------------------

def test_absaetze_je_kapitel_und_je_minute() -> None:
    cues = st.parse_cues(_lies("asr_en.json3"), "json3")
    absaetze = st.build_paragraphs(cues, [{"start_time": 0.0}, {"start_time": 60.0}])
    assert absaetze == [
        {"start": 1.2, "text": "good morning everyone welcome to this side event. [Music]"},
        {"start": 65.0, "text": "concessional finance and sukuk the NCQG is 300 billion"},
        {"start": 300.5, "text": "thank you"},
    ]
    assert st.render_text(absaetze).split("\n\n")[1] == "[00:01:05] concessional finance and sukuk the NCQG is 300 billion"


def test_absatz_wartet_bis_zur_obergrenze_auf_ein_satzende() -> None:
    cues = [st.Cue(0.0, 5.0, "eins"), st.Cue(70.0, 75.0, "zwei."), st.Cue(80.0, 85.0, "drei"), st.Cue(175.0, 180.0, "vier")]
    assert [p["text"] for p in st.build_paragraphs(cues)] == ["eins zwei.", "drei", "vier"]
    assert st.timestamp(3725.9) == "01:02:05"


def test_abdeckung_nennt_anteil_und_groesste_luecke() -> None:
    cues = st.parse_cues(_lies("asr_en.json3"), "json3")
    abdeckung = st.coverage(cues, 310)
    assert abdeckung == {
        "beginn": 1.2, "ende": 305.0, "anteil": 0.984, "groesste_luecke": 170.5, "groesste_luecke_bei": 130.0,
        "zeilen": 6, "woerter": 20,
    }
    assert st.coverage(cues, None)["anteil"] is None


# --- fetch_subtitles und Route ----------------------------------------------------------------

def test_fetch_laedt_nur_die_gewaehlte_spur_und_kein_medium(tmp_path: Any) -> None:
    FakeYoutubeDL.info = _info()
    data = media_subtitle_routes.fetch_subtitles(URL, str(tmp_path))
    opts = FakeYoutubeDL.seen_opts[-1]
    assert opts["skip_download"] is True and opts["ignore_no_formats_error"] is True
    assert opts["writesubtitles"] is True and opts["writeautomaticsub"] is True
    assert opts["noplaylist"] is True
    assert len(FakeYoutubeDL.geladen) == 1 and FakeYoutubeDL.geladen[0]["ext"] == "json3"
    assert (data["sprache"], data["art"], data["spur"], data["format"]) == ("en", "automatisch", "en-orig", "json3")
    assert data["text"].startswith("[00:00:01] good morning everyone")
    assert data["abdeckung"]["anteil"] == 0.984
    assert data["metadata"]["upload_date"] == "2026-11-10"
    assert [c["title"] for c in data["metadata"]["chapters"]] == ["Opening remarks", "Panel"]


def test_fetch_leere_spur_ist_ein_fehler_mit_grund(tmp_path: Any) -> None:
    FakeYoutubeDL.info = _info()
    FakeYoutubeDL.datei = {}
    with pytest.raises(st.NoSubtitleTrack) as fehler:
        media_subtitle_routes.fetch_subtitles(URL, str(tmp_path))
    assert fehler.value.grund == st.SPUR_LEER
    FakeYoutubeDL.datei = {"json3": '{"events": []}'}
    with pytest.raises(st.NoSubtitleTrack) as fehler:
        media_subtitle_routes.fetch_subtitles(URL, str(tmp_path))
    assert fehler.value.grund == st.SPUR_LEER


def test_route_liefert_transkript_und_gibt_cookies_weiter(client: Any) -> None:
    FakeYoutubeDL.info = _info()
    resp = client.post("/api/media/subtitles", json={"url": URL, "cookies": COOKIES}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["art"] == "automatisch"
    assert len(body["data"]["absaetze"]) == 3
    cookiefile = FakeYoutubeDL.seen_opts[-1]["cookiefile"]
    assert not os.path.exists(cookiefile)
    assert "geheim-abc" not in resp.get_data(as_text=True)


def test_route_ohne_spur_422_mit_grund_und_verfuegbaren_spuren(client: Any) -> None:
    FakeYoutubeDL.info = _info(automatic_captions={"de": _spur("de", tlang=True)})
    resp = client.post("/api/media/subtitles", json={"url": URL}, headers=AUTH)
    assert resp.status_code == 422
    error = resp.get_json()["error"]
    assert error["code"] == "SUBTITLES_NOT_AVAILABLE"
    assert error["details"]["grund"] == "NUR_UEBERSETZTE_SPUREN"
    assert error["details"]["verfuegbar"]["automatisch_uebersetzt"] == 1
    assert FakeYoutubeDL.geladen == []


@pytest.mark.parametrize("payload, code", [
    ({}, "MISSING_URL"),
    ({"url": URL, "sprache": 5}, "INVALID_SPRACHE"),
    ({"url": URL, "sprache": "en; rm"}, "INVALID_SPRACHE"),
    ({"url": URL, "cookies": ""}, "INVALID_COOKIES"),
])
def test_route_eingabefehler(client: Any, payload: Dict[str, Any], code: str) -> None:
    resp = client.post("/api/media/subtitles", json=payload, headers=AUTH)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == code


def test_route_deutet_youtube_fehler_wie_die_anderen_routen(client: Any, monkeypatch: Any) -> None:
    class Scheitert(FakeYoutubeDL):
        def extract_info(self, url: str, download: bool = False) -> Any:
            raise media_routes.yt_dlp.utils.DownloadError("ERROR: [youtube] hCEHADgvf8A: Sign in to confirm you’re not a bot.")

    monkeypatch.setattr(media_routes.yt_dlp, "YoutubeDL", Scheitert)
    resp = client.post("/api/media/subtitles", json={"url": URL}, headers=AUTH)
    assert resp.status_code == 422
    error = resp.get_json()["error"]
    assert error["code"] == "SUBTITLES_NOT_AVAILABLE"
    assert error["details"]["grund"] == "YOUTUBE_ANMELDUNG_FEHLT"


def test_route_verlangt_anmeldung_am_dienst(client: Any) -> None:
    assert client.post("/api/media/subtitles", json={"url": URL}).status_code in (401, 403)
