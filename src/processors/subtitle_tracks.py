"""
@fileoverview Untertitelspur eines Videos waehlen, lesen und zum Transkript aufbereiten (reine Funktionen).

@description
Fuer POST /api/media/subtitles: Viele Videoseiten tragen fertige Untertitel. Wer nur den Wortlaut
braucht, spart damit den Download der Tonspur und die Transkription.

Drei Schritte, alle ohne Netz und ohne yt-dlp-Import:

1. `choose_track` waehlt aus den Feldern `subtitles` (von Hand gepflegt) und `automatic_captions`
   von yt-dlp genau eine Spur. Vorrang: die von Hand gepflegte Spur der gewuenschten Sprache, sonst
   die automatische Spur in der Originalsprache. Uebersetzte automatische Spuren (YouTube: `tlang` in
   der Adresse) sind maschinelle Uebersetzungen der automatischen Spur und gelten nie als Transkript.
   Der Live-Chat (`live_chat`) ist keine Untertitelspur.
2. `parse_cues` liest die Formate json3 (YouTube), vtt und srt zu Zeilen mit Zeitmarke. Automatische
   Untertitel wiederholen im vtt jede Zeile (rollende Anzeige); die Wiederholungen fallen weg.
3. `build_paragraphs` zieht die kurzen Zeilen zu Absaetzen zusammen, rund einer je Minute und einer
   je Kapitelbeginn, und behaelt je Absatz die Zeitmarke. `coverage` sagt, wie viel der Laufzeit
   die Spur abdeckt und wo die groesste Luecke liegt (fruehere Livestreams).

Kein stiller Rueckfall: gibt es keine brauchbare Spur, wirft `choose_track` `NoSubtitleTrack` mit
einem Grund-Code; ein unlesbares Format wirft `ValueError`.

@module processors.subtitle_tracks
@usedIn
- src.api.routes.media_subtitle_routes
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

# Formate, die `parse_cues` lesen kann, in der Reihenfolge des Vorrangs. json3 hat je Zeile nur neue
# Woerter; vtt und srt brauchen die Entdopplung.
READABLE_FORMATS: Tuple[str, ...] = ("json3", "vtt", "srt")

# Schluessel in `subtitles`, die keine Untertitel sind (YouTube: Chat-Mitschrift eines Livestreams).
NON_SUBTITLE_KEYS = frozenset({"live_chat", "comments", "danmaku"})

ART_MANUELL = "manuell"
ART_AUTOMATISCH = "automatisch"

# Grund-Codes fuer `error.details.grund` der Route.
KEINE_UNTERTITEL = "KEINE_UNTERTITEL"
NUR_UEBERSETZTE_SPUREN = "NUR_UEBERSETZTE_SPUREN"
SPRACHE_NICHT_EINDEUTIG = "SPRACHE_NICHT_EINDEUTIG"
FORMAT_NICHT_LESBAR = "FORMAT_NICHT_LESBAR"
SPUR_LEER = "SPUR_LEER"
VIDEO_LAEUFT_NOCH = "VIDEO_LAEUFT_NOCH"

# Ein Absatz beginnt fruehestens nach dieser Zeit neu; bis zur Obergrenze wartet er auf ein Satzende.
PARAGRAPH_SECONDS = 60.0
PARAGRAPH_MAX_SECONDS = 90.0
_SENTENCE_END = re.compile(r"[.!?…][\"')\]»”]*$")


class NoSubtitleTrack(ValueError):
    """Es gibt keine Spur, die als Transkript taugt. `grund` ist einer der Codes oben."""

    def __init__(self, grund: str, message: str, verfuegbar: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.grund = grund
        self.verfuegbar: Dict[str, Any] = verfuegbar or {}


@dataclass(frozen=True)
class ChosenTrack:
    """Die gewaehlte Spur: `key` ist der Schluessel bei yt-dlp, `entry` der Eintrag mit `url` und `ext`."""

    key: str
    sprache: str
    art: str
    entry: Dict[str, Any]
    verfuegbar: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Cue:
    """Eine Untertitelzeile: Beginn und Ende in Sekunden, Text ohne Auszeichnung."""

    start: float
    end: float
    text: str


# --------------------------------------------------------------------------- Spur waehlen

def _base_language(code: str) -> str:
    """`en-US`, `en_GB`, `en-orig` -> `en`; fuer den Vergleich von Sprachen."""
    return re.split(r"[-_]", code.strip().lower(), maxsplit=1)[0]


def _readable_entry(entries: Any) -> Optional[Dict[str, Any]]:
    """Der Eintrag im besten lesbaren Format (mit Adresse oder mitgeliefertem Inhalt), sonst None."""
    if not isinstance(entries, list):
        return None
    for ext in READABLE_FORMATS:
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("ext") != ext:
                continue
            if isinstance(entry.get("url"), str) and entry["url"] or isinstance(entry.get("data"), str):
                return entry
    return None


def _formats(entries: Any) -> List[str]:
    if not isinstance(entries, list):
        return []
    return sorted({str(e.get("ext")) for e in entries if isinstance(e, dict) and e.get("ext")})


def _is_translated(entries: Any) -> bool:
    """YouTube kennzeichnet maschinell uebersetzte Spuren mit `tlang` in der Adresse."""
    if not isinstance(entries, list):
        return False
    for entry in entries:
        url = entry.get("url") if isinstance(entry, dict) else None
        if isinstance(url, str) and "tlang" in parse_qs(urlsplit(url).query):
            return True
    return False


def _manual_tracks(subtitles: Any) -> Dict[str, Any]:
    if not isinstance(subtitles, dict):
        return {}
    return {
        key: entries for key, entries in subtitles.items()
        if isinstance(key, str) and key not in NON_SUBTITLE_KEYS and isinstance(entries, list) and entries
    }


def _original_automatic_tracks(automatic: Any) -> Dict[str, Any]:
    """Automatische Spuren in der Originalsprache, je Sprache einmal: `<sprache>-orig` zuerst, sonst jede Spur ohne `tlang`."""
    if not isinstance(automatic, dict):
        return {}
    marked = {k: v for k, v in automatic.items() if isinstance(k, str) and k.endswith("-orig") and isinstance(v, list) and v}
    if marked:
        return marked
    return {
        k: v for k, v in automatic.items()
        if isinstance(k, str) and isinstance(v, list) and v and not _is_translated(v)
    }


def _match_language(tracks: Dict[str, Any], sprache: str) -> Optional[str]:
    """Schluessel der Spur in `sprache`: genauer Treffer vor gleicher Grundsprache (`en` trifft `en-US`)."""
    wanted = sprache.strip().lower()
    for key in tracks:
        if key.lower() == wanted:
            return key
    for key in tracks:
        if _base_language(key) == _base_language(wanted):
            return key
    return None


def choose_track(info: Dict[str, Any], sprache: Optional[str] = None) -> ChosenTrack:
    """Waehlt die Spur, die als Transkript gilt. Wirft `NoSubtitleTrack`, wenn es keine gibt.

    Args:
        info: Antwort von yt-dlp (`subtitles`, `automatic_captions`, `language`, `live_status`).
        sprache: gewuenschte Sprache (z. B. `en`); ohne Angabe gilt die Originalsprache des Videos.
    """
    if info.get("live_status") in ("is_live", "is_upcoming"):
        raise NoSubtitleTrack(VIDEO_LAEUFT_NOCH, "Das Video laeuft noch oder ist erst angekuendigt; Untertitel gibt es erst zur Aufzeichnung")

    manual = _manual_tracks(info.get("subtitles"))
    automatic_all = info.get("automatic_captions") if isinstance(info.get("automatic_captions"), dict) else {}
    originals = _original_automatic_tracks(automatic_all)
    video_language = info.get("language") if isinstance(info.get("language"), str) and info.get("language") else None
    original_language = _base_language(next(iter(originals))) if len(originals) == 1 else (
        _base_language(video_language) if video_language else None
    )
    verfuegbar: Dict[str, Any] = {
        "manuell": sorted(manual),
        "automatisch_original": sorted({_base_language(k) for k in originals}),
        "automatisch_uebersetzt": sum(1 for k, v in automatic_all.items() if k not in originals and _is_translated(v)),
        "originalsprache": original_language,
    }

    wanted = sprache.strip() if isinstance(sprache, str) and sprache.strip() else original_language
    manual_key: Optional[str] = None
    if wanted:
        manual_key = _match_language(manual, wanted)
    elif len(manual) == 1:
        # Sprache des Videos unbekannt und genau eine gepflegte Spur: es gibt nichts zu waehlen.
        manual_key = next(iter(manual))
    if manual_key is not None:
        return _chosen(manual_key, _base_language(manual_key), ART_MANUELL, manual[manual_key], verfuegbar)

    auto_key: Optional[str] = None
    if len(originals) == 1:
        auto_key = next(iter(originals))
    elif len(originals) > 1 and wanted:
        auto_key = _match_language(originals, wanted)
    if auto_key is not None:
        return _chosen(auto_key, _base_language(auto_key), ART_AUTOMATISCH, originals[auto_key], verfuegbar)

    if len(originals) > 1 or (manual and not wanted):
        raise NoSubtitleTrack(
            SPRACHE_NICHT_EINDEUTIG,
            "Mehrere Spuren, aber die Sprache des Videos ist unbekannt; bitte `sprache` angeben. "
            f"Von Hand gepflegt: {', '.join(sorted(manual)) or 'keine'}; automatisch: {', '.join(sorted(originals)) or 'keine'}",
            verfuegbar,
        )
    if manual:
        raise NoSubtitleTrack(
            KEINE_UNTERTITEL,
            f"Keine Spur in der Sprache '{wanted}' und keine automatische Spur in der Originalsprache. "
            f"Von Hand gepflegt gibt es: {', '.join(sorted(manual))}",
            verfuegbar,
        )
    if verfuegbar["automatisch_uebersetzt"] > 0:
        raise NoSubtitleTrack(
            NUR_UEBERSETZTE_SPUREN,
            "Das Video traegt nur maschinell uebersetzte Spuren; die Spur in der Originalsprache fehlt",
            verfuegbar,
        )
    raise NoSubtitleTrack(KEINE_UNTERTITEL, "Das Video traegt keine Untertitel, weder von Hand gepflegt noch automatisch erzeugt", verfuegbar)


def _chosen(key: str, sprache: str, art: str, entries: Any, verfuegbar: Dict[str, Any]) -> ChosenTrack:
    entry = _readable_entry(entries)
    if entry is None:
        raise NoSubtitleTrack(
            FORMAT_NICHT_LESBAR,
            f"Die Spur '{key}' gibt es nur in den Formaten {', '.join(_formats(entries)) or 'unbekannt'}; lesbar sind {', '.join(READABLE_FORMATS)}",
            verfuegbar,
        )
    return ChosenTrack(key=key, sprache=sprache, art=art, entry=entry, verfuegbar=verfuegbar)


# ------------------------------------------------------------------------------ Formate lesen

_TAG = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"\s+")
_INVISIBLE = re.compile("[​‌‍⁠﻿]")
_TIME = r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE_TIMING = re.compile(rf"^\s*{_TIME}\s+-->\s+{_TIME}")


def _clean(text: str) -> str:
    return _SPACES.sub(" ", _INVISIBLE.sub("", html.unescape(_TAG.sub("", text)))).strip()


def _seconds(hours: Optional[str], minutes: str, seconds: str, fraction: str) -> float:
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")) / 1000.0


def parse_json3(raw: str) -> List[Cue]:
    """YouTube json3: `events` mit `tStartMs`, `dDurationMs` und `segs[].utf8`. Zeilen ohne Text (Fenster, Umbrueche) fallen weg."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Untertitel im Format json3 sind kein gueltiges JSON") from exc
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        raise ValueError("Untertitel im Format json3 ohne Feld 'events'")
    cues: List[Cue] = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("segs"), list):
            continue
        start_ms = event.get("tStartMs")
        if not isinstance(start_ms, (int, float)):
            continue
        text = _clean("".join(seg["utf8"] for seg in event["segs"] if isinstance(seg, dict) and isinstance(seg.get("utf8"), str)))
        if not text:
            continue
        duration_ms = event.get("dDurationMs") if isinstance(event.get("dDurationMs"), (int, float)) else 0
        cues.append(Cue(start=start_ms / 1000.0, end=(start_ms + duration_ms) / 1000.0, text=text))
    return cues


def parse_vtt(raw: str) -> List[Cue]:
    """WebVTT und SRT. Jede Textzeile zaehlt einmal: die rollende Anzeige automatischer Untertitel wiederholt die Vorzeile."""
    cues: List[Cue] = []
    start = end = 0.0
    in_cue = False
    last_line = ""
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        timing = _CUE_TIMING.match(line)
        if timing:
            groups = timing.groups()
            start, end = _seconds(*groups[:4]), _seconds(*groups[4:])
            in_cue = True
            continue
        if line == "":
            in_cue = False
            continue
        if not line.strip():
            continue  # Zeile nur aus Leerzeichen: Fuellzeile der rollenden Anzeige, der Block geht weiter
        if not in_cue:
            continue  # Kopf (WEBVTT, Kind:, Language:), NOTE-Bloecke, Nummern der SRT-Zeilen
        text = _clean(line)
        if not text or text == last_line:
            continue
        last_line = text
        cues.append(Cue(start=start, end=end, text=text))
    return cues


def parse_cues(raw: str, ext: str) -> List[Cue]:
    """Liest eine Untertiteldatei im Format `ext`. Wirft `ValueError` bei fremdem Format."""
    if ext == "json3":
        return parse_json3(raw)
    if ext in ("vtt", "srt"):
        return parse_vtt(raw)
    raise ValueError(f"Untertitelformat '{ext}' ist nicht lesbar; lesbar sind {', '.join(READABLE_FORMATS)}")


# -------------------------------------------------------------------------- Aufbereiten

def _chapter_starts(chapters: Any) -> List[float]:
    starts: List[float] = []
    if isinstance(chapters, list):
        for chapter in chapters:
            value = chapter.get("start_time") if isinstance(chapter, dict) else None
            if isinstance(value, (int, float)) and value > 0:
                starts.append(float(value))
    return sorted(set(starts))


def build_paragraphs(cues: Sequence[Cue], chapters: Any = None) -> List[Dict[str, Any]]:
    """Zieht Zeilen zu Absaetzen zusammen: neu je Kapitelbeginn und rund je Minute, bevorzugt nach einem Satzende."""
    boundaries = _chapter_starts(chapters)
    paragraphs: List[Dict[str, Any]] = []
    words: List[str] = []
    paragraph_start = 0.0
    next_boundary = 0
    for cue in cues:
        crossed = False
        while next_boundary < len(boundaries) and cue.start >= boundaries[next_boundary]:
            next_boundary += 1
            crossed = True
        if words:
            age = cue.start - paragraph_start
            sentence_done = bool(_SENTENCE_END.search(words[-1]))
            if crossed or age >= PARAGRAPH_MAX_SECONDS or (age >= PARAGRAPH_SECONDS and sentence_done):
                paragraphs.append({"start": round(paragraph_start, 3), "text": " ".join(words)})
                words = []
        if not words:
            paragraph_start = cue.start
        words.append(cue.text)
    if words:
        paragraphs.append({"start": round(paragraph_start, 3), "text": " ".join(words)})
    return paragraphs


def timestamp(seconds: float) -> str:
    """Sekunden als `hh:mm:ss`."""
    total = int(max(0.0, seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def render_text(paragraphs: Sequence[Dict[str, Any]]) -> str:
    """Absaetze als Text, jeder mit seiner Zeitmarke: `[00:01:00] ...`."""
    return "\n\n".join(f"[{timestamp(p['start'])}] {p['text']}" for p in paragraphs)


def coverage(cues: Sequence[Cue], duration: Any) -> Dict[str, Any]:
    """Wie viel der Laufzeit die Spur abdeckt: erste und letzte Zeile, groesste Luecke, Anteil an der Dauer (None ohne Dauer)."""
    if not cues:
        raise ValueError("Keine Untertitelzeilen")
    first, last = cues[0].start, max(c.end for c in cues)
    gap, gap_at, previous_end = 0.0, 0.0, cues[0].start
    for cue in cues:
        if cue.start - previous_end > gap:
            gap, gap_at = cue.start - previous_end, previous_end
        previous_end = max(previous_end, cue.end)
    total = float(duration) if isinstance(duration, (int, float)) and duration > 0 else None
    return {
        "beginn": round(first, 3),
        "ende": round(last, 3),
        "anteil": round(min(1.0, last / total), 3) if total else None,
        "groesste_luecke": round(gap, 3),
        "groesste_luecke_bei": round(gap_at, 3),
        "zeilen": len(cues),
        "woerter": sum(len(c.text.split()) for c in cues),
    }
