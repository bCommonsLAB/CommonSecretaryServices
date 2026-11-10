"""
Tests fuer AP-06 (Abhaengigkeiten und Docker-Basis, Befunde H5 und H4).

- requirements.lock deckt jede direkte Abhaengigkeit aus requirements.txt ab und passt zu deren Angabe.
- Jedes Paket im Lockfile ist exakt gepinnt und hat Pruefsummen.
- Die als verwundbar gemeldeten Pakete liegen mindestens auf der behobenen Version.
- Das Dockerfile installiert aus dem Lockfile mit Hash-Pruefung, pinnt das Basisimage per Digest
  und zieht nichts nachtraeglich hoch.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "requirements.txt"
LOCK = REPO_ROOT / "requirements.lock"
DOCKERFILE = REPO_ROOT / "Dockerfile"

# Behobene Versionen laut pip-audit (13.10.2026 und 10.11.2026)
MINIMUM_VERSIONS = {
    "pillow": "13.0.0",
    "pymongo": "4.18.2",
    "flask": "3.1.3",
    "pytest": "9.0.3",
}


def _direct_requirements() -> List[Requirement]:
    result: List[Requirement] = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            result.append(Requirement(line))
    return result


def _lock_entries() -> Dict[str, Dict[str, object]]:
    """Liest das Lockfile: Name -> {"version": Version, "hashes": Anzahl}."""
    entries: Dict[str, Dict[str, object]] = {}
    current = None
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if match and not raw.startswith(" "):
            current = canonicalize_name(match.group(1))
            entries[current] = {"version": Version(match.group(2)), "hashes": 0}
        elif line.startswith("--hash=sha256:") and current:
            entries[current]["hashes"] = int(entries[current]["hashes"]) + 1  # type: ignore[call-overload]
        else:
            assert raw.startswith(" "), f"Nicht exakt gepinnte Zeile im Lockfile: {raw!r}"
    return entries


def test_lockfile_ist_vollstaendig_gepinnt_mit_hashes() -> None:
    entries = _lock_entries()
    assert len(entries) > 50
    ohne_hash = [name for name, entry in entries.items() if not entry["hashes"]]
    assert not ohne_hash, f"Pakete ohne Pruefsumme: {ohne_hash}"


def test_lockfile_deckt_direkte_abhaengigkeiten_ab() -> None:
    entries = _lock_entries()
    probleme: List[str] = []
    for requirement in _direct_requirements():
        name = canonicalize_name(requirement.name)
        if name not in entries:
            probleme.append(f"{requirement.name}: fehlt im Lockfile")
        elif not requirement.specifier.contains(entries[name]["version"], prereleases=True):  # type: ignore[arg-type]
            probleme.append(f"{requirement.name}: Lockfile hat {entries[name]['version']}, verlangt ist {requirement.specifier}")
    assert not probleme, "requirements.lock neu erzeugen (docs/deployment/abhaengigkeiten.md):\n" + "\n".join(probleme)


def test_requirements_ohne_installationsoptionen() -> None:
    """Optionen wie --only-binary in einer Zeile brechen pip-audit und das Erzeugen des Lockfiles."""
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        code = line.split("#", 1)[0]
        assert " --" not in code and not code.startswith("--"), f"Option in requirements.txt: {line!r}"


def test_verwundbare_pakete_sind_angehoben() -> None:
    entries = _lock_entries()
    for name, minimum in MINIMUM_VERSIONS.items():
        assert entries[name]["version"] >= Version(minimum), f"{name} {entries[name]['version']} < {minimum}"  # type: ignore[operator]


def test_dockerfile_installiert_aus_lockfile() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", code, flags=re.M), "Basisimage nicht per Digest gepinnt"
    assert "--require-hashes" in code and "requirements.lock" in code
    assert "requirements.txt" not in code, "Image darf nicht aus requirements.txt installieren"
    assert "--upgrade" not in code, "Kein nachtraegliches pip install --upgrade im Build"
    assert "apt-get upgrade" in code
