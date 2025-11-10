"""
@fileoverview Image-to-Text Utilities - OpenAI Vision API integration for image text extraction

@description
Image-to-text utilities with OpenAI Vision API. This module provides the Image2TextService
class for converting images to structured Markdown text using OpenAI's Vision API.

Main functionality:
- Convert images to structured Markdown text
- Extract text from images using OpenAI Vision API
- Support for PDF pages (via PyMuPDF)
- Image preprocessing and optimization
- LLM request tracking

Features:
- OpenAI Vision API integration
- Structured Markdown output
- PDF page support
- Image preprocessing (scaling, optimization)
- LLM tracking integration
- Error handling and retry logic

@module utils.image2text_utils

@exports
- Image2TextService: Class - Service for image-to-text conversion with OpenAI Vision API

@usedIn
- src.processors.pdf_processor: Uses Image2TextService for PDF page OCR
- src.processors.imageocr_processor: Uses Image2TextService for image OCR
- LLM-based OCR processing

@dependencies
- External: openai - OpenAI Vision API client
- External: Pillow (PIL) - Image processing
- External: PyMuPDF (fitz) - PDF page extraction (optional)
- Internal: src.core.config - Config for OpenAI configuration
- Internal: src.core.models.llm - LLMRequest for tracking
- Internal: src.utils.logger - ProcessingLogger
- Internal: src.core.exceptions - ProcessingError
"""

import base64
import io
import time
from typing import Optional, Dict, Any
from pathlib import Path
from PIL import Image
try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    fitz = None  # type: ignore

from openai import OpenAI
from openai.types.chat import ChatCompletion

from src.utils.logger import ProcessingLogger
from src.core.models.llm import LLMRequest
from src.core.config import Config
from src.core.exceptions import ProcessingError


class Image2TextService:
    """
    Service für die Konvertierung von Bildern zu strukturiertem Markdown-Text
    mit OpenAI Vision API.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, processor_name: Optional[str] = None):
        """
        Initialisiert den Image2TextService.
        
        Args:
            config: Optional, Konfiguration für den Service
            processor_name: Optional, Name des aufrufenden Processors
        """
        # Lade Konfiguration
        app_config = Config()
        self.openai_config = config or app_config.get('processors', {}).get('openai', {})
        
        # OpenAI Client initialisieren
        api_key = self.openai_config.get('api_key')
        if not api_key:
            raise ProcessingError("OpenAI API Key nicht gefunden in der Konfiguration (processors.openai.api_key)")
        
        self.client = OpenAI(api_key=api_key)
        self.model = self.openai_config.get('vision_model', 'gpt-4o')
        self.processor_name = processor_name or 'Image2TextService'
        
        # Bildkonfiguration
        self.max_image_size = self.openai_config.get('max_image_size', 2048)
        self.image_quality = self.openai_config.get('image_quality', 85)
        
        # Standard-Prompt für Markdown-Konvertierung
        self.default_prompt = """Konvertiere den Text dieses Bildes in strukturiertes Markdown.

Wichtige Anforderungen:
1. Verarbeite die Texte in der Reihenfolge, wie ein Leser sie wahrnehmen würde (von oben nach unten, links nach rechts)
2. Füge Bilder als Platzhalter mit detaillierter Bildbeschreibung ein: ![Bildbeschreibung](placeholder.jpg)
3. Füge mehrspaltige Texte sinnvoll aneinander
4. Konvertiere Tabellen in Markdown-Tabellen
5. Verwende passende Markdown-Strukturen (Überschriften, Listen, etc.)
6. Behalte die logische Struktur und Hierarchie des Dokuments bei
7. Extrahiere ALLE sichtbaren Texte, auch kleine Details wie Fußnoten oder Bildunterschriften

Antworte NUR mit dem Markdown-Text, ohne zusätzliche Erklärungen."""

    def convert_pdf_page_to_image(self, page: Any, dpi: int = 300) -> bytes:
        """
        Konvertiert eine PDF-Seite zu einem Bild für Vision API.
        
        Args:
            page: PyMuPDF Page-Objekt
            dpi: Auflösung in DPI
            
        Returns:
            bytes: JPEG-Bilddaten
        """
        try:
            if fitz is None:
                raise ProcessingError("PyMuPDF (fitz) ist nicht installiert oder nicht verfügbar")
            # Berechne Skalierungsfaktor für gewünschte DPI
            scale_factor = dpi / 72  # PyMuPDF verwendet 72 DPI als Basis
            matrix = fitz.Matrix(scale_factor, scale_factor)
            
            # Erstelle Pixmap mit hoher Auflösung
            pix = page.get_pixmap(matrix=matrix)
            
            # Konvertiere zu PIL Image
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            
            # Größe prüfen und ggf. reduzieren
            if img.width > self.max_image_size or img.height > self.max_image_size:
                img.thumbnail((self.max_image_size, self.max_image_size), Image.Resampling.LANCZOS)
            
            # Konvertiere zu JPEG-Bytes
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=self.image_quality, optimize=True)
            
            # Ressourcen freigeben
            del pix
            
            return img_buffer.getvalue()
            
        except Exception as e:
            raise ProcessingError(f"Fehler beim Konvertieren der PDF-Seite: {str(e)}")

    def convert_image_file_to_bytes(self, image_path: Path) -> bytes:
        """
        Konvertiert eine Bilddatei zu JPEG-Bytes für Vision API.
        
        Args:
            image_path: Pfad zur Bilddatei
            
        Returns:
            bytes: JPEG-Bilddaten
        """
        try:
            with Image.open(image_path) as img:
                # Konvertiere zu RGB falls nötig
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Größe prüfen und ggf. reduzieren
                if img.width > self.max_image_size or img.height > self.max_image_size:
                    img.thumbnail((self.max_image_size, self.max_image_size), Image.Resampling.LANCZOS)
                
                # Konvertiere zu JPEG-Bytes
                img_buffer = io.BytesIO()
                img.save(img_buffer, format="JPEG", quality=self.image_quality, optimize=True)
                return img_buffer.getvalue()
                
        except Exception as e:
            raise ProcessingError(f"Fehler beim Konvertieren der Bilddatei {image_path}: {str(e)}")

    def extract_text_from_image_bytes(
        self,
        image_bytes: bytes,
        custom_prompt: Optional[str] = None,
        logger: Optional[ProcessingLogger] = None
    ) -> tuple[str, LLMRequest]:
        """
        Extrahiert Text aus einem Bild mit OpenAI Vision API.
        
        Args:
            image_bytes: JPEG-Bilddaten
            custom_prompt: Optionaler benutzerdefinierter Prompt
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            tuple[str, LLMRequest]: Extrahierter Markdown-Text und LLM-Request-Info
        """
        try:
            prompt = custom_prompt or self.default_prompt
            
            if logger:
                logger.debug(f"Starte Vision API mit Modell {self.model}")
            
            # Bild zu Base64 kodieren
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # Zeitmessung starten
            start_time = time.time()
            
            # OpenAI Vision API aufrufen
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4000,
                temperature=0.1
            )
            
            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000
            
            if not response.choices or not response.choices[0].message:
                raise ProcessingError("Keine gültige Antwort von OpenAI Vision API erhalten")
            
            extracted_text = response.choices[0].message.content or ""
            
            # Bereinige Markdown-Codeblöcke
            extracted_text = self.clean_markdown_response(extracted_text)
            
            if logger:
                logger.debug(f"Vision API erfolgreich, {len(extracted_text)} Zeichen extrahiert")
            
            # LLM-Request für Tracking erstellen
            llm_request = LLMRequest(
                model=self.model,
                purpose="image_to_markdown",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration,
                processor=self.processor_name
            )
            
            return extracted_text, llm_request
            
        except Exception as e:
            if logger:
                logger.error(f"Fehler bei Vision API: {str(e)}")
            raise ProcessingError(f"Fehler bei der Bild-zu-Text-Konvertierung: {str(e)}")

    def extract_text_from_pdf_page(
        self,
        page: Any,
        page_num: int,
        custom_prompt: Optional[str] = None,
        logger: Optional[ProcessingLogger] = None
    ) -> tuple[str, LLMRequest]:
        """
        Extrahiert Text aus einer PDF-Seite mit Vision API.
        
        Args:
            page: PyMuPDF Page-Objekt
            page_num: Seitennummer (für Logging)
            custom_prompt: Optionaler benutzerdefinierter Prompt
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            tuple[str, LLMRequest]: Extrahierter Markdown-Text und LLM-Request-Info
        """
        if logger:
            logger.debug(f"Konvertiere PDF-Seite {page_num} zu Bild für Vision API")
        
        # Konvertiere Seite zu Bild
        image_bytes = self.convert_pdf_page_to_image(page)
        
        # Extrahiere Text mit Vision API
        return self.extract_text_from_image_bytes(image_bytes, custom_prompt, logger)

    def extract_text_from_image_file(
        self,
        image_path: Path,
        custom_prompt: Optional[str] = None,
        logger: Optional[ProcessingLogger] = None
    ) -> tuple[str, LLMRequest]:
        """
        Extrahiert Text aus einer Bilddatei mit Vision API.
        
        Args:
            image_path: Pfad zur Bilddatei
            custom_prompt: Optionaler benutzerdefinierter Prompt
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            tuple[str, LLMRequest]: Extrahierter Markdown-Text und LLM-Request-Info
        """
        if logger:
            logger.debug(f"Konvertiere Bilddatei {image_path.name} für Vision API")
        
        # Konvertiere Bild zu Bytes
        image_bytes = self.convert_image_file_to_bytes(image_path)
        
        # Extrahiere Text mit Vision API
        return self.extract_text_from_image_bytes(image_bytes, custom_prompt, logger)

    def create_enhanced_prompt(
        self,
        context: Optional[Dict[str, Any]] = None,
        document_type: Optional[str] = None,
        language: str = "de"
    ) -> str:
        """
        Erstellt einen erweiterten Prompt basierend auf Kontext und Dokumenttyp.
        
        Args:
            context: Optionaler Kontext
            document_type: Typ des Dokuments (z.B. "scientific_paper", "presentation")
            language: Zielsprache für die Ausgabe
            
        Returns:
            str: Erweiterter Prompt
        """
        base_prompt = self.default_prompt
        
        # Sprachspezifische Anpassung
        if language != "de":
            base_prompt = base_prompt.replace(
                "Konvertiere den Text dieses Bildes in strukturiertes Markdown.",
                f"Convert the text of this image to structured Markdown in {language}."
            )
        
        # Dokumenttyp-spezifische Erweiterungen
        if document_type == "scientific_paper":
            base_prompt += "\n\nBesondere Aufmerksamkeit auf: Formeln, Referenzen, Abbildungsunterschriften, Tabellen mit Daten."
        elif document_type == "presentation":
            base_prompt += "\n\nBesondere Aufmerksamkeit auf: Folientitel, Bullet Points, Diagramme, Sprecher-Notizen."
        elif document_type == "technical_document":
            base_prompt += "\n\nBesondere Aufmerksamkeit auf: Code-Snippets, technische Spezifikationen, Diagramme, Schritt-für-Schritt-Anleitungen."
        
        # Kontext-spezifische Erweiterungen
        if context:
            if context.get('extract_formulas'):
                base_prompt += "\n\nExtrahiere mathematische Formeln in LaTeX-Notation."
            if context.get('preserve_formatting'):
                base_prompt += "\n\nBehalte die ursprüngliche Formatierung so genau wie möglich bei."
            if context.get('focus_on_tables'):
                base_prompt += "\n\nLege besonderen Fokus auf die korrekte Extraktion und Formatierung von Tabellen."
        
        return base_prompt

    def clean_markdown_response(self, text: str) -> str:
        """
        Bereinigt die LLM-Antwort von überflüssigen Markdown-Codeblöcken.
        
        Args:
            text: Roher Text von der Vision API
            
        Returns:
            str: Bereinigter Markdown-Text
        """
        if not text:
            return text
        
        # Entferne ```markdown am Anfang
        if text.startswith("```markdown"):
            text = text[11:]  # Länge von "```markdown"
        
        # Entferne ``` am Anfang (falls kein "markdown" dabei)
        elif text.startswith("```"):
            text = text[3:]
        
        # Entferne ``` am Ende
        if text.endswith("```"):
            text = text[:-3]
        
        # Entferne führende und abschließende Leerzeichen/Zeilenumbrüche
        text = text.strip()
        
        return text 