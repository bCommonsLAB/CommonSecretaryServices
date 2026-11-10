"""
Gemeinsame Test-Einstellungen.

Namensauflösung für den SSRF-Schutz (AP-12): Tests dürfen nicht vom DNS der Umgebung abhängen.
Hostnamen lösen deshalb fest auf eine öffentliche Dokumentationsadresse auf; IP-Adressen und
``localhost`` gehen an die echte Auflösung. Einzelne Tests können ``FAKE_DNS`` ergänzen.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict, List

import pytest

# Öffentliche Adresse für beliebige Hostnamen in Tests (kein Abruf findet statt).
PUBLIC_TEST_IP = "93.184.215.14"
FAKE_DNS: Dict[str, List[str]] = {}


def _fake_getaddrinfo(host: str, port: int) -> List[Any]:
    name = host.lower().rstrip(".")
    if name in FAKE_DNS:
        addresses = FAKE_DNS[name]
        if not addresses:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    else:
        try:
            ipaddress.ip_address(name)
            return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except ValueError:
            pass
        if name == "localhost" or any(ch.isdigit() for ch in name.split(".")[-1]) or name.startswith("0x"):
            # localhost und Kurzschreibweisen wie 127.1 oder 0x7f.0.0.1: echte Auflösung
            return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [PUBLIC_TEST_IP]
    result: List[Any] = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        result.append((family, socket.SOCK_STREAM, 6, "", (address, port)))
    return result


@pytest.fixture(autouse=True)
def _deterministic_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.utils import ssrf

    FAKE_DNS.clear()
    monkeypatch.setattr(ssrf, "_getaddrinfo", _fake_getaddrinfo)
    monkeypatch.delenv("FETCH_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("WEBHOOK_ALLOWED_HOSTS", raising=False)
