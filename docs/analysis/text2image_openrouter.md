# Analyse: Text2Image-Integration mit OpenRouter

## Ausgangslage

Der Client benötigt einen Image-Generator, der durch Text formulierte Bilder generiert und zurückliefert. OpenRouter.ai bietet Zugriff auf verschiedene Image-Generierungs-Modelle, die über eine OpenAI-kompatible API erreichbar sind.

**Wichtige Erkenntnisse:**
- OpenRouter unterstützt Bildgenerierung über `chat/completions` mit dem `modalities` Parameter (`["image", "text"]`)
- Nicht über eine separate `images.generate` API wie OpenAI
- Die Antwort enthält base64-kodierte Bilder im `images` Feld der Chat-Completion-Response
- Nur Modelle mit `"image"` in `output_modalities` unterstützen Bildgenerierung

## Anforderungen

1. **Use-Case in LLM-Config**: Neuer Use-Case `text2image` für Modell-Konfiguration
2. **Provider-Integration**: OpenRouter Provider erweitern um Bildgenerierung
3. **Prozessor**: Dedizierter `Text2ImageProcessor` nach Audio-Muster
4. **API-Endpoint**: Synchroner Endpoint `/api/text2image/generate` mit JSON-Request/Response
5. **Response-Format**: Standardisiertes Format mit Base64-Bild + Metadaten
6. **LLM-Tracking**: Vollständiges Tracking wie bei anderen Use-Cases

## 3 Varianten

### Variante A: Provider-Methode `text2image()` mit Chat-Completions (EMPFOHLEN)

**Implementierung:**
- Neue Methode `text2image()` im `LLMProvider` Protocol
- OpenRouter-Implementierung nutzt `client.chat.completions.create()` mit `modalities=["image", "text"]`
- Response-Parsing extrahiert Bilder aus `response.choices[0].message.images`
- Rückgabe: `tuple[bytes, LLMRequest]` (Bild-Bytes + Tracking)

**Pro:**
- Konsistent mit bestehender Provider-Architektur
- Klare Trennung: Provider = API-Abstraktion, Processor = Business-Logik
- Einfach erweiterbar für andere Provider (OpenAI, Mistral, etc.)
- LLM-Tracking direkt im Provider integriert

**Contra:**
- OpenRouter-spezifische Response-Struktur muss geparst werden
- Nicht identisch mit OpenAI's `images.generate` API

**Entscheidung:** ✅ **Variante A wird implementiert**

### Variante B: Eigenes Utility-Modul für Images-API

**Implementierung:**
- Neues Modul `src/utils/text2image_utils.py` mit `Text2ImageService`
- Provider bleibt schlank, ruft Utility auf
- Utility enthält alle API-Logik

**Pro:**
- Provider bleibt schlank
- Utility kann für verschiedene Provider wiederverwendet werden

**Contra:**
- Doppelte Abstraktionsebene (Provider + Utility)
- Weniger konsistent mit bestehender Architektur (z.B. `vision()` ist direkt im Provider)
- LLM-Tracking muss durchgereicht werden

**Entscheidung:** ❌ Nicht gewählt (inkonsistent mit bestehender Architektur)

### Variante C: Generierung über Chat-Completion ohne Modalities

**Implementierung:**
- Nutzt normale Chat-Completion ohne `modalities` Parameter
- Modell generiert Text-Beschreibung, die dann extern zu Bild konvertiert wird

**Pro:**
- Funktioniert mit allen Chat-Modellen

**Contra:**
- Nicht wirklich Bildgenerierung, sondern Text-zu-Text
- Benötigt zusätzlichen Service für Text-zu-Bild-Konvertierung
- Nicht das gewünschte Verhalten

**Entscheidung:** ❌ Nicht gewählt (nicht das gewünschte Verhalten)

## Implementierungsdetails

### Provider-Methode Signatur

```python
def text2image(
    self,
    prompt: str,
    model: str,
    size: str = "1024x1024",
    quality: str = "standard",
    n: int = 1,
    **kwargs: Any
) -> tuple[bytes, LLMRequest]:
    """
    Generiert ein Bild aus einem Text-Prompt.
    
    Args:
        prompt: Text-Prompt für Bildgenerierung
        model: Zu verwendendes Modell
        size: Bildgröße (z.B. "1024x1024", "1792x1024", "1024x1792")
        quality: Qualität ("standard" oder "hd")
        n: Anzahl der Bilder (default: 1)
        **kwargs: Zusätzliche Parameter
        
    Returns:
        tuple[bytes, LLMRequest]: Bild-Bytes (PNG) und LLM-Request-Info
        
    Raises:
        ProcessingError: Wenn Bildgenerierung fehlschlägt
    """
```

### Response-Struktur

```python
@dataclass
class Text2ImageData:
    """Daten für Text2Image-Response"""
    image_base64: str  # Base64-kodiertes PNG-Bild
    image_format: str  # "png"
    size: str  # "1024x1024"
    model: str  # Verwendetes Modell
    prompt: str  # Original-Prompt
    seed: Optional[int] = None  # Seed für Reproduzierbarkeit
```

### Cache-Key

Cache-Key basiert auf:
- Prompt (normalisiert)
- Modell
- Size
- Quality
- n

Format: `text2image:{hash(prompt+model+size+quality+n)}`

## Konfiguration

### config.yaml

```yaml
llm_config:
  use_cases:
    text2image:
      provider: openrouter
      model: openai/dall-e-3  # Beispiel-Modell

llm_providers:
  openrouter:
    available_models:
      text2image:
        - openai/dall-e-3
        - stability-ai/stable-diffusion-xl-base-1.0
        # Weitere Modelle mit image output_modalities
```

## Nächste Schritte

1. ✅ Use-Case `text2image` zu `UseCase` Enum hinzufügen
2. ✅ Provider-Protocol erweitern
3. ✅ OpenRouter-Provider implementieren
4. ✅ Dataclasses erstellen
5. ✅ Prozessor implementieren
6. ✅ API-Route erstellen
7. ✅ Dokumentation ergänzen
8. ✅ Tests schreiben
