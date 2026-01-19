# Analyse: OpenRouter Text2Image 405

## Kontext
Die OpenRouter-Dokumentation empfiehlt fuer Bildgenerierung den
Chat-Endpoint (`POST /chat/completions`) mit `modalities: ["image","text"]`.
Der Images-Endpoint (`/images/generations`) ist primär fuer OpenAI-Modelle.
Bei Modellen wie `black-forest-labs/flux.2-max` liefert der Images-Endpoint
HTTP 405, was auf ein Endpoint-/Modell-Mismatch hindeutet.

## Varianten
### Variante A: Chat-Endpoint fuer alle Image-Modelle
- Nutze `/chat/completions` mit `modalities` wie in der OpenRouter-Doku.
- Vermeidet 405 bei Nicht-OpenAI-Modellen.
- Groesste Kompatibilitaet laut offizieller Dokumentation.
- Nutze `/images/generations` ausschliesslich fuer `openai/*` Modelle.
- Fuer andere Modelle wird fruehzeitig ein klarer Fehler ausgegeben.
- Sehr stabil, aber keine Unterstuetzung fuer Flux/SDXL ueber OpenRouter.

### Variante B: Images-Endpoint nur fuer OpenAI-Modelle
- Nutze `/images/generations` ausschliesslich fuer `openai/*`.
- Fuer andere Modelle nutze `/chat/completions` mit `modalities`.
- Reduziert 405, erhoeht aber Pfad-Varianz.

### Variante C: Provider-native APIs fuer Nicht-OpenAI-Modelle
- Direkte Calls zu BFL/SDXL APIs fuer Flux/SDXL.
- Hoher Integrationsaufwand, mehr Konfiguration und Tests.

## Entscheidung
Variante A entspricht der offiziellen OpenRouter-Logik und ist der
primaere Pfad. Variante B bleibt als Sonderfall fuer OpenAI-Modelle
moeglich, falls der Images-Endpoint gewuenscht ist.
