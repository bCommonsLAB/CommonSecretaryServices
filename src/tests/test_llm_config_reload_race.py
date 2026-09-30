"""Tests: ``LLMConfigManager.reload_config()`` darf parallele Leser nie ins Leere laufen lassen.

Hintergrund (docs/analysis/llm_config_reload_race.md): Jeder Transformer-Request ruft
``reload_config()`` am geteilten Singleton. Frueher wurde dabei ``_config`` kurz auf
``None`` gesetzt und dann aus MongoDB nachgeladen. Parallele Requests sahen in diesem
Fenster keine Konfiguration, fanden keinen Chat-Provider und fielen aufs
Transkriptionsmodell zurueck („Chat-Completion Provider nicht verfuegbar",
Modell „gpt-transcribe"). Bei sechs gleichzeitigen Uebersetzungsjobs traf das etwa
jede siebte Anfrage.

Die Tests simulieren das Nachladen mit einem kuenstlich langsamen ``_load_config``
und pruefen, dass Leser waehrenddessen immer eine gueltige Konfiguration sehen.

Der Test setzt die Singletons ueber ihre privaten Felder zurueck (``_instance``,
``_config``). Das ist hier Absicht, deshalb ist die Pyright-Pruefung fuer
privaten Zugriff in dieser Datei abgeschaltet.
"""
# pyright: reportPrivateUsage=false

import threading
import time
import unittest
from typing import Any, List, Optional
from unittest.mock import patch

from src.core.llm.config_manager import LLMConfigManager
from src.core.llm.provider_manager import ProviderManager
from src.core.models.llm_config import LLMConfig, ProviderConfig, UseCaseConfig


def _build_config() -> LLMConfig:
    """Kleine, gueltige Konfiguration mit einem Chat-Completion-Use-Case."""
    return LLMConfig(
        providers={"openai": ProviderConfig(name="openai", api_key="test-key")},
        use_cases={
            "chat_completion": UseCaseConfig(
                use_case="chat_completion", provider="openai", model="gpt-test"
            )
        },
    )


def _slow_load_config(self: LLMConfigManager) -> None:
    """Ersatz fuer ``_load_config``: simuliert den MongoDB-Round-Trip.

    Baut die Konfiguration erst fertig und weist sie dann zu — genau wie das
    Original. Die Pause davor macht das Zeitfenster gross genug, damit das
    alte ``self._config = None`` in ``reload_config`` zuverlaessig auffaellt.
    """
    time.sleep(0.005)
    self._config = _build_config()


class TestReloadConfigRace(unittest.TestCase):
    """Leser duerfen waehrend eines Reloads nie ``None`` sehen."""

    def setUp(self) -> None:
        # Singleton fuer den Test frisch aufsetzen und danach wiederherstellen.
        self._alte_instanz: Optional[LLMConfigManager] = LLMConfigManager._instance
        LLMConfigManager._instance = None
        self._patcher = patch.object(LLMConfigManager, "_load_config", _slow_load_config)
        self._patcher.start()
        self.manager = LLMConfigManager()

    def tearDown(self) -> None:
        self._patcher.stop()
        LLMConfigManager._instance = self._alte_instanz

    def test_initial_config_is_loaded(self) -> None:
        self.assertEqual(self.manager.get_model_for_use_case("chat_completion"), "gpt-test")

    def test_readers_never_see_empty_config_during_reload(self) -> None:
        """Ein Thread laedt in Schleife neu, mehrere Threads lesen parallel.

        Vor dem Fix lieferte ``get_model_for_use_case`` sporadisch ``None``;
        nach dem Fix darf das nie passieren.
        """
        stop = threading.Event()
        leere_treffer: List[Optional[str]] = []
        lese_zaehler: List[int] = [0]

        def reloader() -> None:
            for _ in range(30):
                self.manager.reload_config()

        def reader() -> None:
            while not stop.is_set():
                model = self.manager.get_model_for_use_case("chat_completion")
                lese_zaehler[0] += 1
                if model is None:
                    leere_treffer.append(model)

        reader_threads = [threading.Thread(target=reader) for _ in range(6)]
        for t in reader_threads:
            t.start()
        reload_thread = threading.Thread(target=reloader)
        reload_thread.start()
        reload_thread.join()
        stop.set()
        for t in reader_threads:
            t.join()

        # Sicherstellen, dass die Leser ueberhaupt waehrend der Reloads aktiv waren.
        self.assertGreater(lese_zaehler[0], 30)
        self.assertEqual(
            leere_treffer, [],
            f"{len(leere_treffer)} Lesezugriffe sahen waehrend des Reloads keine Konfiguration",
        )

    def test_config_is_fresh_after_reload(self) -> None:
        """Reload liefert eine neue Konfigurations-Instanz (kein stiller No-Op)."""
        alt = self.manager._config
        self.manager.reload_config()
        self.assertIsNot(alt, self.manager._config)
        self.assertEqual(self.manager.get_model_for_use_case("chat_completion"), "gpt-test")


class _DummyProvider:
    """Minimaler Provider fuer den Cache-Test; braucht kein echtes Protocol."""

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        self.api_key = api_key


class TestProviderCacheRace(unittest.TestCase):
    """``get_provider`` darf bei gleichzeitigem ``clear_cache`` keinen KeyError werfen."""

    PROVIDER_NAME = "_race_test_provider"

    def setUp(self) -> None:
        self.pm = ProviderManager()
        self.pm.register_provider_class(self.PROVIDER_NAME, _DummyProvider)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.pm.clear_cache()
        ProviderManager._provider_classes.pop(self.PROVIDER_NAME, None)

    def test_get_provider_survives_concurrent_clear_cache(self) -> None:
        stop = threading.Event()
        fehler: List[BaseException] = []

        def clearer() -> None:
            for _ in range(500):
                self.pm.clear_cache()

        def getter() -> None:
            while not stop.is_set():
                try:
                    provider = self.pm.get_provider(self.PROVIDER_NAME, api_key="k")
                    self.assertIsNotNone(provider)
                except BaseException as exc:  # noqa: BLE001 - wir wollen jeden Fehler sehen
                    fehler.append(exc)

        getters = [threading.Thread(target=getter) for _ in range(4)]
        for t in getters:
            t.start()
        clear_thread = threading.Thread(target=clearer)
        clear_thread.start()
        clear_thread.join()
        stop.set()
        for t in getters:
            t.join()

        self.assertEqual(fehler, [], f"Fehler bei parallelem Cache-Leeren: {fehler[:3]}")


if __name__ == "__main__":
    unittest.main()
