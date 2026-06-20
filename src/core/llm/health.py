"""
@fileoverview LLM Health Service - Availability checks for LLM operations and endpoints

@description
Stellt einen schlanken Health-Check für LLM-Operationen bereit. Für jeden
Use-Case wird der tatsächlich konfigurierte Provider/Modell (MongoDB-first über
den LLMConfigManager) aufgelöst und geprüft:

1. config:        Provider registriert? aktiviert? API-Key vorhanden?
2. config_source: stammt die aktive Konfiguration aus MongoDB oder ist sie
                  (still) auf config.yaml zurückgefallen? (Selbstdiagnose)
3. connectivity:  billige Erreichbarkeits-/Auth-Probe beim Provider
                  (provider.health_check(), z. B. GET /models)
4. credit:        nur OpenRouter — verbleibendes Guthaben (USD) über
                  /api/v1/key bzw. /api/v1/credits

Endpunkte sind teilweise kaskadierend (ein Processor ruft andere auf). Der
Health-Check pro Endpoint bildet deshalb die *transitive Hülle* der benötigten
Use-Cases und meldet den schlechtesten Teilstatus.

Überlast-/Kapazitätssignale sind hier bewusst NICHT enthalten (dafür gibt es
separate Strategien).

@module core.llm.health

@exports
- LLMHealthService: Class - Health-Check-Service für Use-Cases und Endpunkte
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .use_cases import UseCase
from .config_manager import LLMConfigManager
from .provider_manager import ProviderManager

logger = logging.getLogger(__name__)

# Schwelle (USD), unter der OpenRouter-Guthaben als "low" (= degraded) gilt.
OPENROUTER_CREDIT_LOW_THRESHOLD_USD: float = 5.0

# Time-to-live (Sekunden) für gecachte Health-Ergebnisse pro Use-Case.
# Verhindert, dass häufiges Polling die Provider mit Probes überflutet.
DEFAULT_CACHE_TTL_S: int = 30

# Use-Cases, die ein Processor *direkt* aufruft.
# (verifiziert über get_provider_for_use_case-Aufrufe im Code)
PROCESSOR_DIRECT_USE_CASES: Dict[str, List[UseCase]] = {
    "transformer": [UseCase.CHAT_COMPLETION],
    "audio": [UseCase.TRANSCRIPTION],
    "imageocr": [UseCase.IMAGE2TEXT],
    "pdf": [UseCase.OCR_PDF],
    "text2image": [UseCase.TEXT2IMAGE],
    "image_analyzer": [UseCase.IMAGE_ANALYSIS],
    "rag": [UseCase.EMBEDDING],
}

# Kaskade: welche anderen Processors ein Endpoint/Processor aufruft.
# (verifiziert über die Processor-Imports/Instanziierungen)
PROCESSOR_DEPENDENCIES: Dict[str, List[str]] = {
    "audio": ["transformer"],
    "video": ["audio", "transformer"],
    "youtube": ["audio", "transformer"],
    "imageocr": ["transformer"],
    "pdf": ["imageocr", "transformer"],
    "metadata": ["transformer"],
    "story": ["transformer"],
    "track": ["transformer"],
    "event": ["track", "transformer"],
    "session": ["video", "pdf", "transformer"],
}

# Alle bekannten Endpoint-Namen (Vereinigung aus beiden Maps).
KNOWN_ENDPOINTS: List[str] = sorted(
    set(PROCESSOR_DIRECT_USE_CASES.keys()) | set(PROCESSOR_DEPENDENCIES.keys())
)

# Reihenfolge der Status (kleiner = schlechter). Für "schlechtester gewinnt".
_STATUS_ORDER: Dict[str, int] = {
    "unavailable": 0,
    "degraded": 1,
    "unknown": 2,
    "healthy": 3,
}


def _now_iso() -> str:
    """Aktueller UTC-Zeitstempel als ISO-8601-String."""
    return datetime.now(timezone.utc).isoformat()


class LLMHealthService:
    """
    Health-Check-Service für LLM-Use-Cases und (kaskadierende) Endpunkte.

    Die Auflösung Provider/Modell erfolgt ausschließlich über den
    LLMConfigManager – also exakt denselben Pfad, den auch die Processors zur
    Laufzeit verwenden. Damit kann der Health-Check nie etwas anderes melden als
    das, was eine echte Operation tatsächlich verwenden würde.
    """

    def __init__(self, cache_ttl_s: int = DEFAULT_CACHE_TTL_S) -> None:
        """
        Args:
            cache_ttl_s: TTL für gecachte Use-Case-Ergebnisse (Sekunden).
        """
        self._cache_ttl_s = cache_ttl_s
        # use_case_value -> (expires_at_epoch, result_dict)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    # ------------------------------------------------------------------ #
    # Kaskade                                                            #
    # ------------------------------------------------------------------ #
    def required_use_cases(self, endpoint: str) -> List[UseCase]:
        """
        Liefert die *transitive* Menge der Use-Cases, die ein Endpoint benötigt
        (inklusive der Use-Cases aller kaskadierend aufgerufenen Processors).

        Args:
            endpoint: Endpoint-/Processor-Name (z. B. "session", "pdf").

        Returns:
            Liste der benötigten Use-Cases (Reihenfolge stabil, ohne Duplikate).
        """
        seen: Set[str] = set()
        result: List[UseCase] = []

        def visit(name: str) -> None:
            if name in seen:
                return
            seen.add(name)
            for uc in PROCESSOR_DIRECT_USE_CASES.get(name, []):
                if uc not in result:
                    result.append(uc)
            for dep in PROCESSOR_DEPENDENCIES.get(name, []):
                visit(dep)

        visit(endpoint)
        return result

    # ------------------------------------------------------------------ #
    # Use-Case-Check                                                     #
    # ------------------------------------------------------------------ #
    def check_use_case(
        self,
        use_case: Union[UseCase, str],
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Prüft die Verfügbarkeit eines einzelnen Use-Cases.

        Args:
            use_case: Use-Case (Enum oder String).
            use_cache: Wenn True, wird ein noch gültiges Cache-Ergebnis genutzt.

        Returns:
            Dict mit status, provider, model, config_source und checks.
        """
        uc = use_case if isinstance(use_case, UseCase) else UseCase(str(use_case))
        key = uc.value
        now = time.time()

        if use_cache and key in self._cache:
            expires_at, cached = self._cache[key]
            if now < expires_at:
                return cached

        result = self._check_use_case_uncached(uc)
        self._cache[key] = (now + self._cache_ttl_s, result)
        return result

    def _check_use_case_uncached(self, uc: UseCase) -> Dict[str, Any]:
        cfg = LLMConfigManager()
        result: Dict[str, Any] = {
            "use_case": uc.value,
            "provider": None,
            "model": None,
            "model_id": None,
            "status": "unknown",
            "config_source": "unknown",
            "checks": {},
            "detail": "",
            "checked_at": _now_iso(),
        }

        # 1) Effektive Auflösung (das, was zur Laufzeit verwendet wird).
        uc_config = None
        try:
            uc_config = cfg.get_use_case_config(uc)
        except Exception as exc:  # defensiv – Config-Manager soll nie crashen
            logger.warning("get_use_case_config(%s) fehlgeschlagen: %s", uc.value, exc)

        if not uc_config or not uc_config.provider or not uc_config.model:
            result["status"] = "unavailable"
            result["checks"]["config"] = {
                "ok": False,
                "detail": (
                    f"Use-Case '{uc.value}' ist weder in MongoDB noch in "
                    f"config.yaml konfiguriert."
                ),
            }
            result["detail"] = "Use-Case nicht konfiguriert"
            return result

        provider_name = uc_config.provider
        model = uc_config.model
        model_id = f"{provider_name}/{model}"
        result["provider"] = provider_name
        result["model"] = model
        result["model_id"] = model_id

        # 2) Selbstdiagnose: stammt die aktive Config aus MongoDB oder Fallback?
        result["config_source"] = self._diagnose_config_source(uc, model_id)

        # 3) Config-Checks (kostenlos, ohne Netzwerk).
        config_check = self._check_config(cfg, provider_name, model_id)
        result["checks"]["config"] = config_check
        if not config_check["ok"]:
            result["status"] = "unavailable"
            result["detail"] = config_check["detail"]
            return result

        # 4) Connectivity-/Credit-Probe (Netzwerk, billig, gecacht).
        connectivity, credit = self._probe_provider(cfg, uc)
        result["checks"]["connectivity"] = connectivity
        if credit is not None:
            result["checks"]["credit"] = credit

        # 5) Gesamtstatus des Use-Cases ableiten.
        result["status"], result["detail"] = self._derive_status(connectivity, credit)
        return result

    # ------------------------------------------------------------------ #
    # Teilprüfungen                                                      #
    # ------------------------------------------------------------------ #
    def _check_config(
        self, cfg: LLMConfigManager, provider_name: str, model_id: str
    ) -> Dict[str, Any]:
        """Reine Konfigurations-Prüfung (kein Netzwerk)."""
        check: Dict[str, Any] = {"ok": True, "detail": ""}

        provider_registered = ProviderManager().is_provider_registered(provider_name)
        check["provider_registered"] = provider_registered

        provider_config = None
        try:
            provider_config = cfg.get_provider_config(provider_name)
        except Exception:
            provider_config = None

        if provider_config is None:
            check["ok"] = False
            check["detail"] = f"Provider '{provider_name}' nicht in der Konfiguration gefunden."
            check["model_in_catalog"] = self._model_in_catalog(model_id)
            return check

        api_key = getattr(provider_config, "api_key", "") or ""
        enabled = bool(getattr(provider_config, "enabled", False))
        api_key_present = bool(api_key) and api_key != "not-configured"
        check["enabled"] = enabled
        check["api_key_present"] = api_key_present
        # Informativ: Modell im MongoDB-Katalog vorhanden? (kein Ausschlusskriterium)
        check["model_in_catalog"] = self._model_in_catalog(model_id)

        if not provider_registered:
            check["ok"] = False
            check["detail"] = f"Provider '{provider_name}' ist nicht registriert."
        elif not enabled:
            check["ok"] = False
            check["detail"] = f"Provider '{provider_name}' ist deaktiviert."
        elif not api_key_present:
            check["ok"] = False
            check["detail"] = (
                f"API-Key für Provider '{provider_name}' fehlt "
                f"(Umgebungsvariable nicht gesetzt)."
            )
        else:
            check["detail"] = "Provider konfiguriert, API-Key vorhanden."
        return check

    def _probe_provider(
        self, cfg: LLMConfigManager, uc: UseCase
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Billige Erreichbarkeits-/Guthaben-Probe über provider.health_check()."""
        connectivity: Dict[str, Any] = {
            "reachable": None,
            "latency_ms": None,
            "detail": "nicht geprüft",
        }
        credit: Optional[Dict[str, Any]] = None

        try:
            provider = cfg.get_provider_for_use_case(uc)
        except Exception as exc:
            # z. B. ProcessingError: Paket fehlt / Provider nicht erstellbar
            connectivity = {
                "reachable": False,
                "latency_ms": None,
                "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
            return connectivity, credit

        health_check = getattr(provider, "health_check", None)
        if not callable(health_check):
            connectivity["detail"] = "Provider bietet keine aktive Probe (health_check) an."
            return connectivity, credit

        try:
            probe = health_check() or {}
            connectivity = {
                "reachable": probe.get("reachable"),
                "latency_ms": probe.get("latency_ms"),
                "detail": probe.get("detail", ""),
            }
            probe_credit = probe.get("credit")
            if probe_credit is not None:
                credit = self._evaluate_credit(probe_credit)
        except Exception as exc:
            connectivity = {
                "reachable": False,
                "latency_ms": None,
                "detail": f"Probe fehlgeschlagen: {type(exc).__name__}: {str(exc)[:200]}",
            }
        return connectivity, credit

    @staticmethod
    def _evaluate_credit(probe_credit: Dict[str, Any]) -> Dict[str, Any]:
        """Bewertet das vom Provider gemeldete Guthaben (OpenRouter)."""
        remaining = probe_credit.get("remaining_usd")
        status = "unknown"
        if remaining is not None:
            try:
                remaining_val = float(remaining)
                if remaining_val <= 0:
                    status = "insufficient"
                elif remaining_val < OPENROUTER_CREDIT_LOW_THRESHOLD_USD:
                    status = "low"
                else:
                    status = "ok"
            except (TypeError, ValueError):
                status = "unknown"
        return {
            "status": status,
            "remaining_usd": remaining,
            "threshold_usd": OPENROUTER_CREDIT_LOW_THRESHOLD_USD,
            "detail": probe_credit.get("detail", ""),
        }

    @staticmethod
    def _derive_status(
        connectivity: Dict[str, Any], credit: Optional[Dict[str, Any]]
    ) -> Tuple[str, str]:
        """Leitet den Use-Case-Status aus Connectivity + Credit ab."""
        reachable = connectivity.get("reachable")
        credit_status = credit.get("status") if credit else None

        if reachable is False:
            return "unavailable", f"Provider nicht erreichbar: {connectivity.get('detail')}"
        if credit_status == "insufficient":
            return "unavailable", "Kein Guthaben mehr beim Provider (Quota erschöpft)."
        if credit_status == "low":
            return (
                "degraded",
                f"Guthaben niedrig (< {OPENROUTER_CREDIT_LOW_THRESHOLD_USD} USD).",
            )
        if reachable is None:
            return (
                "healthy",
                "Konfiguration ok; aktive Erreichbarkeitsprüfung für diesen Provider "
                "nicht verfügbar.",
            )
        return "healthy", "Verfügbar."

    # ------------------------------------------------------------------ #
    # MongoDB-Selbstdiagnose                                             #
    # ------------------------------------------------------------------ #
    def _diagnose_config_source(self, uc: UseCase, effective_model_id: str) -> str:
        """
        Bestimmt, ob die aktive Use-Case-Konfiguration aus MongoDB stammt oder
        (still) auf config.yaml zurückgefallen ist – und ob der MongoDB-Wert
        evtl. neuer ist als der geladene (stale cache).
        """
        live_model_id = None
        mongodb_reachable = True
        try:
            from ..mongodb.llm_model_repository import LLMUseCaseConfigRepository

            live_model_id = LLMUseCaseConfigRepository().get_current_model(uc.value)
        except Exception:
            mongodb_reachable = False

        if not mongodb_reachable:
            # MongoDB nicht erreichbar -> Quelle der aktiven Config unbekannt.
            return "unknown (MongoDB nicht erreichbar)"

        if not live_model_id:
            # MongoDB hat diesen Use-Case nicht -> effektiv kommt aus config.yaml.
            return "config_yaml"

        if effective_model_id == live_model_id:
            return "mongodb"

        # MongoDB hat einen anderen Wert als aktuell aktiv:
        if self._model_in_catalog(live_model_id):
            # Wert wäre nutzbar -> geladener Cache ist veraltet.
            return "mongodb (stale: reload_config nötig)"
        # MongoDB-Modell fehlt im Katalog -> _load_config verwirft es -> Fallback.
        return "config_yaml (Fallback: MongoDB-Modell nicht im llm_models-Katalog)"

    @staticmethod
    def _model_in_catalog(model_id: Optional[str]) -> Optional[bool]:
        """True/False, ob model_id im llm_models-Katalog liegt; None bei Fehler."""
        if not model_id:
            return None
        try:
            from ..mongodb.llm_model_repository import LLMModelRepository

            return LLMModelRepository().get_model(model_id) is not None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Aggregierte Checks                                                 #
    # ------------------------------------------------------------------ #
    def check_all(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Prüft alle konfigurierten/relevanten Use-Cases und fasst sie pro
        Endpoint (kaskadenbewusst) zusammen.
        """
        cfg = LLMConfigManager()
        targets: Set[str] = set()
        try:
            targets |= set(cfg.get_all_use_cases().keys())
        except Exception:
            pass
        for ucs in PROCESSOR_DIRECT_USE_CASES.values():
            for uc in ucs:
                targets.add(uc.value)

        use_cases: Dict[str, Any] = {}
        overall = "healthy"
        for ucv in sorted(targets):
            try:
                res = self.check_use_case(ucv, use_cache=use_cache)
            except Exception as exc:
                res = {"use_case": ucv, "status": "unknown", "detail": f"Check-Fehler: {exc}"}
            use_cases[ucv] = res
            overall = self._worse(overall, res.get("status", "unknown"))

        endpoints: Dict[str, Any] = {}
        for endpoint in KNOWN_ENDPOINTS:
            endpoints[endpoint] = self._summarize_endpoint(endpoint, use_cases)

        return {
            "status": overall if use_cases else "unknown",
            "checked_at": _now_iso(),
            "use_cases": use_cases,
            "endpoints": endpoints,
        }

    def check_endpoint(self, endpoint: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Prüft einen einzelnen (ggf. kaskadierenden) Endpoint.

        Args:
            endpoint: Endpoint-/Processor-Name (z. B. "session", "pdf", "audio").
        """
        ucs = self.required_use_cases(endpoint)
        if not ucs:
            known = endpoint in KNOWN_ENDPOINTS
            return {
                "endpoint": endpoint,
                "status": "no_llm_dependency" if known else "unknown",
                "detail": (
                    "Dieser Endpoint hat keine LLM-Abhängigkeit."
                    if known
                    else f"Unbekannter Endpoint '{endpoint}'. "
                    f"Bekannt: {', '.join(KNOWN_ENDPOINTS)}"
                ),
                "use_cases": [],
                "checked_at": _now_iso(),
            }

        status = "healthy"
        parts: List[Dict[str, Any]] = []
        for uc in ucs:
            res = self.check_use_case(uc, use_cache=use_cache)
            status = self._worse(status, res.get("status", "unknown"))
            parts.append(res)

        return {
            "endpoint": endpoint,
            "status": status,
            "use_cases": parts,
            "checked_at": _now_iso(),
        }

    def _summarize_endpoint(
        self, endpoint: str, use_case_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        ucs = self.required_use_cases(endpoint)
        status = "healthy"
        parts: List[Dict[str, Any]] = []
        for uc in ucs:
            res = use_case_results.get(uc.value, {})
            st = res.get("status", "unknown")
            status = self._worse(status, st)
            parts.append(
                {
                    "use_case": uc.value,
                    "status": st,
                    "provider": res.get("provider"),
                    "model": res.get("model"),
                }
            )
        return {
            "endpoint": endpoint,
            "status": status if ucs else "no_llm_dependency",
            "use_cases": parts,
        }

    @staticmethod
    def _worse(a: str, b: str) -> str:
        """Gibt den schlechteren der beiden Status zurück."""
        return a if _STATUS_ORDER.get(a, 2) <= _STATUS_ORDER.get(b, 2) else b
