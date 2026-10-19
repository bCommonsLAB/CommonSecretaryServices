"""
@fileoverview Security helpers - gemeinsame Bausteine fuer API- und Dashboard-Schutz

@description
Kleine, zustandslose Hilfsfunktionen, die API-Middleware (src/api/auth.py) und
Dashboard-Anmeldung (src/dashboard/auth.py) gemeinsam nutzen.

Leitprinzip (docs/sicherheitsplan-umsetzung.md): Jede Installation ist ohne
Proxy-Konfiguration sicher. Alle Werte werden bei jedem Aufruf frisch aus der
Umgebung gelesen, damit Tests und Neustarts ohne Modul-Reload funktionieren.

@module core.security
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Iterable, List, Optional, Sequence, Union

from flask import Flask

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    """Liest eine boolesche Umgebungsvariable (1/true/yes/on)."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


def env_str(name: str) -> Optional[str]:
    """Liest eine Umgebungsvariable; leere Werte gelten als nicht gesetzt."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def insecure_no_auth_allowed() -> bool:
    """Ausdrueckliche Freigabe fuer Betrieb ohne Anmeldung (nur lokale Entwicklung)."""
    return env_flag("ALLOW_INSECURE_NO_AUTH")


def trusted_proxy_count() -> int:
    """Anzahl vertrauenswuerdiger Proxys vor der Anwendung (Default 0 = keinem Header trauen)."""
    raw = env_str("TRUSTED_PROXY_COUNT")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def apply_proxy_fix(app: Flask) -> None:
    """
    Wertet X-Forwarded-* nur aus, wenn TRUSTED_PROXY_COUNT > 0 gesetzt ist.

    Ohne diese Einstellung bleibt request.remote_addr die direkte Gegenstelle,
    und vom Client gesetzte Forwarded-Header haben keine Wirkung.
    """
    count = trusted_proxy_count()
    if count <= 0 or getattr(app, "_secretary_proxy_fix_applied", False):
        return
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=count, x_proto=count, x_host=count)  # type: ignore[method-assign]
    setattr(app, "_secretary_proxy_fix_applied", True)


def constant_time_equals(given: Optional[str], expected: Optional[str]) -> bool:
    """Zeitkonstanter Vergleich; None oder leer ist nie gleich."""
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def parse_ip_networks(raw: Optional[str]) -> List[IPNetwork]:
    """
    Parst eine komma-, semikolon- oder leerzeichengetrennte Liste von IPs und CIDR-Netzen.

    'localhost' wird zu 127.0.0.1 und ::1. Hostnamen werden ignoriert, weil
    eine Whitelist nur gegen die tatsaechliche Gegenstelle geprueft wird.
    """
    if not raw:
        return []
    networks: List[IPNetwork] = []
    for part in raw.replace(",", " ").replace(";", " ").split():
        entry = part.strip()
        if not entry:
            continue
        if entry.lower() == "localhost":
            networks.append(ipaddress.ip_network("127.0.0.1/32"))
            networks.append(ipaddress.ip_network("::1/128"))
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks


def ip_in_networks(ip: Optional[str], networks: Sequence[IPNetwork]) -> bool:
    """Prueft, ob eine IP-Adresse in einem der Netze liegt."""
    if not ip or not networks:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks if addr.version == net.version)


def is_loopback(ip: Optional[str]) -> bool:
    """True fuer 127.0.0.0/8 und ::1."""
    if not ip:
        return False
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def format_problems(problems: Iterable[str]) -> str:
    """Formatiert Konfigurationsprobleme als Aufzaehlung fuer Log und Konsole."""
    return "\n".join(f"  - {p}" for p in problems)


def redact_uri(uri: Optional[str]) -> str:
    """
    Verbindungsadresse fuer Logs: Passwort aus "scheme://user:pass@host" entfernen.

    Beispiel: "mongodb://admin:geheim@mongodb:27017/db" -> "mongodb://admin:***@mongodb:27017/db"
    """
    if not uri:
        return ""
    import re

    return re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)([^:/@]*):([^@]*)@", r"\1\2:***@", uri)


def insecure_tls_requested() -> bool:
    """PYTHONHTTPSVERIFY=0 (oder false) ist gesetzt."""
    raw = os.environ.get("PYTHONHTTPSVERIFY")
    return raw is not None and raw.strip().lower() in {"0", "false"}


def insecure_tls_allowed() -> bool:
    """
    TLS-Prüfung darf nur abgeschaltet werden, wenn PYTHONHTTPSVERIFY=0 UND
    FLASK_ENV=development gesetzt sind (lokale Entwicklung hinter einem
    TLS-brechenden Proxy). In jedem anderen Fall bleibt die Prüfung an.
    """
    return insecure_tls_requested() and (os.environ.get("FLASK_ENV") or "").strip().lower() == "development"


def tls_verify() -> bool:
    """Wert für ``requests(..., verify=...)`` und ``not nocheckcertificate`` bei yt-dlp."""
    return not insecure_tls_allowed()


def apply_tls_policy() -> str:
    """
    Wendet die TLS-Regel prozessweit an und liefert den Zustand für das Log:
    "verified", "ignored" (PYTHONHTTPSVERIFY=0 ohne FLASK_ENV=development)
    oder "disabled" (Entwicklungsmodus, globaler SSL-Kontext ohne Prüfung).

    Mehrfache Aufrufe sind unschädlich.
    """
    if not insecure_tls_requested():
        return "verified"
    if not insecure_tls_allowed():
        return "ignored"
    import ssl

    ssl._create_default_https_context = ssl._create_unverified_context
    return "disabled"
