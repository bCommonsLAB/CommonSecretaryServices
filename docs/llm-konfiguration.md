# LLM-Konfiguration in CommonSecretaryServices (Multi-Provider)

## Kontext / Ziel
Diese Anwendung unterstützt mehrere LLM-Provider und konfiguriert **Provider + Modell pro Use-Case**.
Das ist bewusst granular (Transkription ≠ Chat ≠ Vision ≠ OCR ≠ Embeddings), weil nicht jeder Provider jeden Use-Case anbietet.

## Architektur (Ist-Zustand)
- **Use-Cases** sind in `src/core/llm/use_cases.py` definiert (z.B. `transcription`, `image2text`, `ocr_pdf`, `chat_completion`, `embedding`).
- **Provider-Definitionen** kommen aus `config/config.yaml` unter `llm_providers.*`:
  - `enabled`, `api_key` (oft `${ENV_VAR}`), optional `base_url`, optional `available_models` pro Use-Case.
- **Use-Case Routing** kommt aus `config/config.yaml` unter `llm_config.use_cases.*`:
  - pro Use-Case: `provider` + `model` (bei `embedding` zusätzlich optional `dimensions`).
- `LLMConfigManager` lädt beide Bereiche und erzeugt Provider-Instanzen über `ProviderManager`.

## Unterstützte Provider

- **OpenAI**: Chat-Completion, Vision, Transcription
- **Mistral**: Chat-Completion, Vision, OCR
- **OpenRouter**: Chat-Completion, Vision (Zugriff auf viele Modelle verschiedener Provider)
- **Ollama**: Chat-Completion, Vision (lokale Installation)
- **VoyageAI**: Embeddings (speziell für RAG/Vector Search) - **NEU integriert**

## Wichtige Beobachtungen / Risiken
- Einige Teile haben **Fallbacks** auf direkte SDK-Calls (z.B. Transkription) – wenn Provider-Konfiguration fehlt, kann trotzdem OpenAI über `processors.*`-Config genutzt werden.
- PDF-OCR hat mehrere Pfade:
  - `UseCase.OCR_PDF` über Provider (Vision/Chat-Completion mit Bildern).
  - Separate “Mistral OCR API” (Files/OCR-Endpunkte) nutzt Umgebungsvariablen wie `MISTRAL_MODEL` und kann die Use-Case-Konfig umgehen.
- `llm_providers` ist auf OpenAI-kompatible Provider ausgelegt (OpenAI/OpenRouter/Ollama) plus nativen Mistral-Client.

## Drei praktikable Vorgehensweisen
1. **UI (Dashboard)**: Provider/Model pro Use-Case auswählen und in `config.yaml` speichern lassen.
2. **Manuell**: `config/config.yaml` bearbeiten + ENV Keys setzen, dann App neu starten oder Konfig neu laden.
3. **Code-basiert**: In Prozessoren/Utilities `LLMConfigManager.get_provider_for_use_case()` verwenden und Use-Case-spezifisch routen (z.B. Chat zu OpenRouter, Vision zu OpenAI, OCR zu Mistral).


