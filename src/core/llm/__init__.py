"""
@fileoverview LLM Core Module - Provider abstraction and configuration

@description
Core module for LLM provider abstraction and configuration management.
Provides unified interface for different LLM providers (OpenAI, Mistral, OpenRouter, Ollama).

@module core.llm
"""

from .protocols import LLMProvider
from .use_cases import UseCase
from .provider_manager import ProviderManager
from .config_manager import LLMConfigManager

# Provider-Registrierung beim Import
from .providers.openai_provider import OpenAIProvider
from .providers.mistral_provider import MistralProvider
from .providers.openrouter_provider import OpenRouterProvider
from .providers.ollama_provider import OllamaProvider

# Registriere Provider beim Import
_provider_manager = ProviderManager()
_provider_manager.register_provider_class("openai", OpenAIProvider)
_provider_manager.register_provider_class("mistral", MistralProvider)
_provider_manager.register_provider_class("openrouter", OpenRouterProvider)
_provider_manager.register_provider_class("ollama", OllamaProvider)

__all__ = [
    'LLMProvider',
    'UseCase',
    'ProviderManager',
    'LLMConfigManager',
    'OpenAIProvider'
]
