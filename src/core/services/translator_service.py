"""
@fileoverview Translator Service - Service for text translation with caching

@description
Translator service for text translation. This service provides a centralized interface
for translating texts using the TransformerProcessor and stores translations in the
TranslationRepository for caching and reuse.

Main functionality:
- Translate texts between languages
- Cache translations in MongoDB
- Retrieve cached translations
- Integration with TransformerProcessor for LLM-based translation

Features:
- Translation caching for performance
- Multi-language support
- Entity-based translation management
- Automatic cache lookup
- LLM-based translation fallback

@module core.services.translator_service

@exports
- TranslatorService: Class - Service for text translation

@usedIn
- Can be used for translation management in processors
- Multilingual content processing

@dependencies
- Internal: src.processors.transformer_processor - TransformerProcessor for translation
- Internal: src.core.mongodb.translation_repository - TranslationRepository for caching
- Internal: src.core.models.transformer - TransformerResponse, OutputFormat
"""

import logging
from typing import Optional

from src.core.models.transformer import TransformerResponse, OutputFormat
from src.core.mongodb.translation_repository import TranslationRepository

# Logger initialisieren
logger = logging.getLogger(__name__)

class TranslatorService:
    """
    Service für die Übersetzung von Texten.
    Stellt eine zentrale Schnittstelle für Übersetzungen bereit und 
    speichert diese im Translation-Repository.
    """
    
    def __init__(self):
        """
        Initialisiert den Translator-Service.
        """
        self.repo = TranslationRepository()
        logger.info("TranslatorService initialisiert")
    
    async def translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str = "en",
        use_cache: bool = True
    ) -> str:
        """
        Übersetzt einen Text in die Zielsprache.
        Verwendet den konfigurierten Übersetzungsdienst und speichert Ergebnisse im Cache.
        
        Args:
            text: Zu übersetzender Text
            target_language: Zielsprache (z.B. "de")
            source_language: Quellsprache (Standard: "en")
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            str: Übersetzter Text
        """
        if source_language == target_language:
            return text
            
        if not text or not text.strip():
            return text
            
        # Bei kurzen Texten können wir eine Entity-ID aus dem Text selbst erstellen
        entity_id = text[:50] if len(text) <= 50 else text[:50] + str(hash(text) % 10000)
        
        if use_cache:
            cached = self.repo.get_translation(
                entity_type="text",
                entity_id=entity_id,
                target_language=target_language,
                original_language=source_language
            )
            
            if cached:
                logger.debug(f"Übersetzung aus Cache verwendet: {entity_id}")
                return cached
        
        translated = await self._perform_translation(text, source_language, target_language)
        
        # Im Repository speichern
        if use_cache:
            self.repo.save_translation(
                entity_type="text",
                entity_id=entity_id,
                original_text=text,
                target_language=target_language,
                translated_text=translated,
                original_language=source_language
            )
            
        return translated
    
    async def translate_entity(
        self,
        entity_type: str,
        entity_id: str,
        text: str,
        target_language: str,
        source_language: str = "en",
        use_cache: bool = True
    ) -> str:
        """
        Übersetzt einen Entity-Text (z.B. Track, Session, etc.) und speichert ihn im Repository.
        
        Args:
            entity_type: Typ der Entity ("track", "session", etc.)
            entity_id: ID der Entity
            text: Zu übersetzender Text
            target_language: Zielsprache (z.B. "de")
            source_language: Quellsprache (Standard: "en")
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            str: Übersetzter Text
        """
            
        if not text or not text.strip():
            return text
        
        if use_cache:
            cached = self.repo.get_translation(
                entity_type=entity_type,
                entity_id=entity_id,
                target_language=target_language,
                original_language=source_language
            )
            
            if cached:
                logger.debug(f"Entity-Übersetzung aus Cache verwendet: {entity_type}/{entity_id}")
                return cached
        
        translated = await self._perform_translation(text, source_language, target_language)
        
        # Im Repository speichern
        if use_cache:
            self.repo.save_translation(
                entity_type=entity_type,
                entity_id=entity_id,
                original_text=text,
                target_language=target_language,
                translated_text=translated,
                original_language=source_language
            )
            
        return translated
    
    async def _perform_translation(self, text: str, source_language: str, target_language: str) -> str:
        """
        Führt die eigentliche Übersetzung durch.
        Verwendet den konfigurierten Übersetzungsdienst.
        
        Args:
            text: Zu übersetzender Text
            source_language: Quellsprache
            target_language: Zielsprache
            
        Returns:
            str: Übersetzter Text
        """
        # Translation-Service holen
        try:
            from src.core.resource_tracking import ResourceCalculator
            from src.processors.transformer_processor import TransformerProcessor
            
            resource_calculator = ResourceCalculator()
            processor = TransformerProcessor(resource_calculator=resource_calculator)
            
            # Übersetzen mit der richtigen transform-Methode
            response: TransformerResponse = processor.transform(
                source_text=text,
                source_language=source_language,
                target_language=target_language,
                target_format=OutputFormat.FILENAME,
                summarize=False,  # Wir wollen übersetzen, nicht zusammenfassen
                use_cache=False  # Cache nutzen, wo möglich
            )
            
            if response and response.data and hasattr(response.data, "text"):
                translated_text = response.data.text
                
                if not translated_text or not translated_text.strip():
                    logger.warning(f"Leere Übersetzung erhalten für: {text[:50]}...")
                    return text
                    
                return translated_text
            else:
                logger.warning(f"Ungültiges Übersetzungsergebnis: {response}")
                return text
            
        except Exception as e:
            logger.error(f"Fehler bei der Übersetzung: {str(e)}")
            return text  # Im Fehlerfall den Originaltext zurückgeben

# Singleton-Instanz
_translator_service: Optional[TranslatorService] = None

def get_translator_service() -> TranslatorService:
    """
    Gibt die Singleton-Instanz des TranslatorService zurück.
    
    Returns:
        TranslatorService: Die Singleton-Instanz
    """
    global _translator_service
    
    if _translator_service is None:
        _translator_service = TranslatorService()
        
    return _translator_service 