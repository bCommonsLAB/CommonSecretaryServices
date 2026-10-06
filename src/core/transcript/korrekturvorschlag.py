"""
@fileoverview Korrekturvorschlag - Prompt und Pruefung fuer Transkript plus Begleittexte

@description
Zweiter Durchgang nach der Transkription: Das Transkript (optional mit
Sprecher-Praefixen) wird gegen Begleittexte gehalten (Einladung mit Sprecherliste,
Folien-Transkripte). Heraus kommen NUR Vorschlaege — Ersetzungen fuer Hoerfehler bei
Namen, Zahlen und Fachbegriffen sowie die Zuordnung Label -> Person. Geschrieben wird
hier nichts; das macht der Mensch im KnowledgeScout nach Bestaetigung.

Zwei Dinge sind hier rein und testbar:

1. ``build_messages`` baut den Prompt. Das Antwortschema steht AUSDRUECKLICH im
   Prompt-Text, weil der Dienst kein schema_json erzwingt.
2. ``parse_vorschlaege`` liest die Antwort und prueft jeden Vorschlag gegen die
   Eingabe: ``alt`` muss genau einmal im Transkript vorkommen (damit die Liste
   unveraendert an ``transkript_korrigieren`` gehen kann), ``zeile`` wird aus dem
   Transkript berechnet statt dem Modell geglaubt, Namen muessen in den
   Begleittexten stehen, ``beleg`` muss aus der festen Menge sein. Was die Pruefung
   nicht besteht, wird mit Begruendung unter ``verworfen`` gemeldet — nicht still.

@module core.transcript.korrekturvorschlag

@exports
- Begleittext, Ersetzung, SprecherZuordnung, Korrekturvorschlag: Dataclasses
- BELEG_PATTERN: erlaubte Belege
- build_messages: Prompt (system + user)
- parse_vorschlaege: Antwort lesen und pruefen
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

BELEG_PATTERN = re.compile(r"^(einladung|folie \d+|selbstvorstellung|unsicher)$")

ANTWORTSCHEMA = """{
  "ersetzungen": [
    {
      "alt": "exakte Zeichenkette aus dem Transkript, kommt dort GENAU EINMAL vor",
      "neu": "korrigierte Zeichenkette",
      "zeile": 12,
      "kontext": "die Transkriptzeile oder ein kurzer Ausschnitt um die Stelle",
      "begruendung": "ein Satz, warum das ein Hoerfehler ist",
      "beleg": "einladung | folie <N> | selbstvorstellung | unsicher"
    }
  ],
  "sprecher": [
    {
      "label": "Sprecher-Label genau wie im Transkript, z.B. Sprecher A oder Stück 2 Sprecher B",
      "name": "Name GENAU wie in einem Begleittext geschrieben",
      "begruendung": "ein Satz, woran die Zuordnung erkennbar ist",
      "beleg": "einladung | folie <N> | selbstvorstellung | unsicher"
    }
  ]
}"""


@dataclass(frozen=True)
class Begleittext:
    """Ein Begleittext: Einladung, Flyer, Folien-Transkript."""

    name: str
    text: str


@dataclass(frozen=True)
class Ersetzung:
    alt: str
    neu: str
    zeile: int
    kontext: str
    begruendung: str
    beleg: str

    def to_dict(self) -> Dict[str, Any]:
        return {"alt": self.alt, "neu": self.neu, "zeile": self.zeile, "kontext": self.kontext,
                "begruendung": self.begruendung, "beleg": self.beleg}


@dataclass(frozen=True)
class SprecherZuordnung:
    label: str
    name: str
    begruendung: str
    beleg: str

    def to_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "name": self.name, "begruendung": self.begruendung, "beleg": self.beleg}


@dataclass(frozen=True)
class Korrekturvorschlag:
    ersetzungen: List[Ersetzung] = field(default_factory=list)
    sprecher: List[SprecherZuordnung] = field(default_factory=list)
    verworfen: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ersetzungen": [e.to_dict() for e in self.ersetzungen],
                "sprecher": [s.to_dict() for s in self.sprecher], "verworfen": list(self.verworfen)}


def _numbered(transkript: str) -> str:
    return "\n".join(f"{i}: {line}" for i, line in enumerate(transkript.split("\n"), start=1))


def build_messages(transkript: str, begleittexte: Sequence[Begleittext], zielsprache: str = "de") -> List[Dict[str, str]]:
    """Baut system- und user-Nachricht. Das Antwortschema steht im Text."""
    system = (
        "Du prüfst ein Audio-Transkript gegen Begleittexte derselben Veranstaltung "
        "(Einladung mit Sprecherliste, Folien-Transkripte). Du schlägst Korrekturen vor, "
        "du schreibst nichts um.\n\n"
        "Regeln:\n"
        "1. ersetzungen nur für wahrscheinliche Hörfehler bei Namen, Zahlen, Orten und "
        "Fachbegriffen, die ein Begleittext belegt. Keine Stiländerungen, keine Grammatik.\n"
        "2. alt ist die exakte Zeichenkette aus dem Transkript und kommt dort GENAU EINMAL vor. "
        "Kommt sie mehrfach vor, erweitere alt um Nachbarwörter, bis sie eindeutig ist; "
        "neu enthält dann dieselben Nachbarwörter.\n"
        "3. sprecher ordnet Sprecher-Labels Personen zu. Nimm NUR Namen, die in einem "
        "Begleittext stehen, in genau dieser Schreibweise. Ist niemand belegbar, lass das Label weg — "
        "es bleibt eine Rolle (z.B. Frage aus dem Publikum).\n"
        "4. beleg ist genau eins von: einladung (steht in der Einladung/Sprecherliste), "
        "folie <N> (Folie oder Seite N eines Folien-Transkripts, z.B. folie 3), "
        "selbstvorstellung (die Person nennt sich im Transkript selbst), unsicher (plausibel, aber nicht belegt).\n"
        "5. zeile ist die Zeilennummer aus dem nummerierten Transkript.\n"
        f"6. begruendung in der Sprache '{zielsprache}', ein Satz.\n"
        "7. Antworte AUSSCHLIESSLICH mit JSON nach diesem Schema, ohne Erklärung davor oder danach, "
        "leere Listen sind erlaubt:\n"
        f"{ANTWORTSCHEMA}"
    )
    parts: List[str] = []
    if begleittexte:
        for i, b in enumerate(begleittexte, start=1):
            parts.append(f"=== Begleittext {i}: {b.name} ===\n{b.text.strip()}")
    else:
        parts.append("=== Keine Begleittexte übergeben: keine Namen zuordnen, nur offensichtliche Zahlenfehler melden ===")
    parts.append(f"=== Transkript (Zeilennummer: Text) ===\n{_numbered(transkript)}")
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


def extract_json(raw: str) -> Dict[str, Any]:
    """Liest das JSON-Objekt aus der Antwort, auch wenn Codeblock-Zeichen oder Text drumherum stehen."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Antwort enthält kein JSON-Objekt: {text[:200]}")
        parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Antwort ist kein JSON-Objekt")
    return parsed


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _beleg(raw: Any) -> Optional[str]:
    beleg = _norm(str(raw or ""))
    return beleg if BELEG_PATTERN.match(beleg) else None


def _line_of(transkript: str, alt: str) -> int:
    offset = transkript.index(alt)
    return transkript.count("\n", 0, offset) + 1


def parse_vorschlaege(raw: str, transkript: str, begleittexte: Sequence[Begleittext]) -> Korrekturvorschlag:
    """Liest die Modellantwort und behaelt nur Vorschlaege, die gegen die Eingabe bestehen."""
    data = extract_json(raw)
    verworfen: List[str] = []
    ersetzungen: List[Ersetzung] = []
    seen_alt: set[str] = set()
    for item in data.get("ersetzungen") or []:
        if not isinstance(item, dict):
            verworfen.append("ersetzung: kein Objekt"); continue
        alt, neu = str(item.get("alt") or ""), str(item.get("neu") or "")
        if not alt.strip() or not neu.strip():
            verworfen.append(f"ersetzung '{alt}': alt oder neu leer"); continue
        if alt == neu:
            verworfen.append(f"ersetzung '{alt}': alt und neu gleich"); continue
        if "\n" in alt:
            verworfen.append(f"ersetzung '{alt}': alt geht über einen Zeilenumbruch"); continue
        count = transkript.count(alt)
        if count != 1:
            verworfen.append(f"ersetzung '{alt}': kommt {count}x im Transkript vor, erwartet genau 1x"); continue
        if alt in seen_alt:
            verworfen.append(f"ersetzung '{alt}': doppelt vorgeschlagen"); continue
        beleg = _beleg(item.get("beleg"))
        if beleg is None:
            verworfen.append(f"ersetzung '{alt}': beleg '{item.get('beleg')}' nicht erlaubt"); continue
        seen_alt.add(alt)
        zeile = _line_of(transkript, alt)
        kontext = str(item.get("kontext") or "").strip() or transkript.split("\n")[zeile - 1].strip()
        ersetzungen.append(Ersetzung(alt, neu, zeile, kontext, str(item.get("begruendung") or "").strip(), beleg))

    begleit_norm = [_norm(b.text) for b in begleittexte]
    sprecher: List[SprecherZuordnung] = []
    seen_label: set[str] = set()
    for item in data.get("sprecher") or []:
        if not isinstance(item, dict):
            verworfen.append("sprecher: kein Objekt"); continue
        label, name = str(item.get("label") or "").strip(), str(item.get("name") or "").strip()
        if not label or not name:
            verworfen.append(f"sprecher '{label}': label oder name leer"); continue
        if label not in transkript:
            verworfen.append(f"sprecher '{label}': Label kommt im Transkript nicht vor"); continue
        if label in seen_label:
            verworfen.append(f"sprecher '{label}': doppelt zugeordnet"); continue
        if not any(_norm(name) in text for text in begleit_norm):
            verworfen.append(f"sprecher '{label}': Name '{name}' steht in keinem Begleittext"); continue
        beleg = _beleg(item.get("beleg"))
        if beleg is None:
            verworfen.append(f"sprecher '{label}': beleg '{item.get('beleg')}' nicht erlaubt"); continue
        seen_label.add(label)
        sprecher.append(SprecherZuordnung(label, name, str(item.get("begruendung") or "").strip(), beleg))
    return Korrekturvorschlag(ersetzungen=ersetzungen, sprecher=sprecher, verworfen=verworfen)
