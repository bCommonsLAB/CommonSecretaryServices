# Analyse: OpenRouter Text2Image Endpoint

## Kontext
Das aktuelle Text2Image-Backend nutzt den OpenAI-kompatiblen Chat-Endpoint
mit `modalities`, was bei OpenRouter zu Parameter-Fehlern fuehrt.
Der Nutzer hat den offiziellen OpenRouter-Images-Endpoint benannt.

## Varianten
### Variante A: OpenRouter Images-Endpoint (`/images/generations`)
- Direkter OpenRouter-Images-Endpoint mit `model`, `prompt`, `size`, `quality`.
- Antwort enthaelt `url` oder optional `b64_json`.
- Implementierung via `client.images.generate(...)`.
- Passt zur synchronen Anforderung und reduziert Modell-Spezialfaelle.

### Variante B: Chat-Endpoint mit `modalities`/`image_config`
- Nutzung von `chat/completions` mit `modalities` und `image_config`.
- Stark modellabhaengig und fehleranfaellig (Parameterabweichungen).
- Bereits Fehler mit `image_config` in der Praxis.

### Variante C: Modell-spezifische Native APIs
- Direkte Calls zu Provider-APIs (z.B. BFL/Flux).
- Erhoehter Integrationsaufwand und divergierende Antworten.
- Schwerer zu testen und zu standardisieren.

## Entscheidung
Variante A ist die stabilste und kompatibelste Option fuer OpenRouter.
Sie folgt dem offiziell dokumentierten Endpoint und reduziert Sonderfaelle.
