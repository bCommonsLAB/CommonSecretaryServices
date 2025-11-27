from typing import Optional, Tuple

from src.core.llm import LLMConfigManager, UseCase


def test_embedding_use_case_present_in_llm_config() -> None:
    """Stellt sicher, dass der Embedding-Use-Case in der LLM-Config vorhanden ist."""
    manager = LLMConfigManager()
    use_case_config = manager.get_use_case_config(UseCase.EMBEDDING)

    assert use_case_config is not None
    assert use_case_config.use_case == UseCase.EMBEDDING.value
    assert isinstance(use_case_config.model, str) and use_case_config.model
    assert isinstance(use_case_config.provider, str) and use_case_config.provider


def test_get_embedding_defaults_returns_consistent_values() -> None:
    """Prüft, dass get_embedding_defaults Modell und Dimensionen konsistent liefert."""
    manager = LLMConfigManager()
    model_name, provider_name, dimensions = manager.get_embedding_defaults()

    # Modell und Provider sind konfiguriert
    assert isinstance(model_name, str) and model_name
    assert isinstance(provider_name, str) and provider_name

    # Dimensionen sind optional, aber wenn gesetzt, dann > 0
    if dimensions is not None:
        assert isinstance(dimensions, int)
        assert dimensions > 0



