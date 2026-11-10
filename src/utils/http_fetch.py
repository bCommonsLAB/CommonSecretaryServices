"""
@fileoverview HTTP fetch - Downloads mit Timeout, Größenlimit und TLS-Prüfung

@description
Arbeitspaket AP-04 aus docs/sicherheitsplan-umsetzung.md (Befunde H2, H6).
Downloads von Request-URLs dürfen einen Worker weder unbegrenzt blockieren
noch die Platte füllen:

- Verbindungs- und Lese-Timeout (``timeout``) plus Gesamtdauer (``max_seconds``)
- Größenlimit wird beim Streamen gezählt, nicht nur aus ``Content-Length`` gelesen
- TLS-Prüfung nach ``src.core.security.tls_verify()``

SSRF-Schutz (AP-12): Ziele werden über ``src.utils.ssrf`` geprüft, interne Adressen sind gesperrt
(Ausnahmen je Installation: ``FETCH_ALLOWED_HOSTS``). ``allow_private=True`` schaltet die Prüfung ab
und ist nur für Tests und fest konfigurierte interne Ziele gedacht, nie für Adressen aus Requests.

@module utils.http_fetch
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import requests

from src.core.security import tls_verify
from src.utils import ssrf

DEFAULT_TIMEOUT: Tuple[float, float] = (10.0, 60.0)
DEFAULT_MAX_SECONDS: float = 1800.0
USER_AGENT = "CommonSecretaryServices"
_CHUNK = 64 * 1024


class DownloadError(Exception):
    """Download abgebrochen (Größe, Dauer oder HTTP-Status)."""


class DownloadTooLarge(DownloadError):
    """Die Antwort ist größer als ``max_bytes``."""


def _open(
    url: str,
    timeout: Tuple[float, float],
    headers: Optional[Dict[str, str]],
    allow_private: bool = False,
) -> requests.Response:
    merged = {"User-Agent": USER_AGENT}
    merged.update(headers or {})
    if allow_private:
        resp = requests.get(url, stream=True, timeout=timeout, headers=merged, verify=tls_verify())
    else:
        # Prüft die Adresse, jede Weiterleitung und die tatsächlich verbundene IP (ssrf.SsrfBlocked).
        resp = ssrf.get(url, stream=True, timeout=timeout, headers=merged, verify=tls_verify())
    resp.raise_for_status()
    return resp


def _check_declared_size(resp: requests.Response, max_bytes: int) -> None:
    declared = resp.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise DownloadTooLarge(f"Datei zu groß: {declared} Bytes (Maximum {max_bytes} Bytes)")


def download_to_file(
    url: str,
    dest: Union[str, "os.PathLike[str]"],
    max_bytes: int,
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    max_seconds: Optional[float] = DEFAULT_MAX_SECONDS,
    headers: Optional[Dict[str, str]] = None,
    allow_private: bool = False,
) -> int:
    """
    Lädt ``url`` nach ``dest`` und liefert die Anzahl Bytes.

    Bei Überschreitung von ``max_bytes`` oder ``max_seconds`` wird abgebrochen
    und die angefangene Datei gelöscht.
    """
    target = Path(dest)
    started = time.monotonic()
    written = 0
    try:
        with _open(url, timeout, headers, allow_private) as resp:
            _check_declared_size(resp, max_bytes)
            with open(target, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        raise DownloadTooLarge(f"Datei zu groß: mehr als {max_bytes} Bytes")
                    if max_seconds is not None and time.monotonic() - started > max_seconds:
                        raise DownloadError(f"Download dauerte länger als {int(max_seconds)} s")
                    fh.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return written


def fetch_bytes(
    url: str,
    max_bytes: int,
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    max_seconds: Optional[float] = DEFAULT_MAX_SECONDS,
    headers: Optional[Dict[str, str]] = None,
    allow_private: bool = False,
) -> bytes:
    """Wie ``download_to_file``, liefert den Inhalt im Speicher."""
    started = time.monotonic()
    parts = []
    total = 0
    with _open(url, timeout, headers, allow_private) as resp:
        _check_declared_size(resp, max_bytes)
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise DownloadTooLarge(f"Datei zu groß: mehr als {max_bytes} Bytes")
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                raise DownloadError(f"Download dauerte länger als {int(max_seconds)} s")
            parts.append(chunk)
    return b"".join(parts)
