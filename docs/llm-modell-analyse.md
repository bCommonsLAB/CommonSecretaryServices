# LLM-Modell-Analyse basierend auf Token-Nutzungsstatistiken

## Datum der Analyse
24. November 2025

## Zusammenfassung
Diese Analyse basiert auf Token-Nutzungsstatistiken von OpenRouter und gibt Empfehlungen für die Modellauswahl in `config/config.yaml`.

## Empfehlungen: Modelle hinzufügen

### 1. Modelle mit sehr starkem Wachstum (Priorität: HOCH)

#### Devstral 2 2512 (free) - MistralAI
- **Token-Nutzung**: 104 Mrd. Tokens
- **Wachstum**: ↑532% (extrem stark!)
- **Besonderheit**: Kostenlos verfügbar
- **OpenRouter-Name**: `mistralai/devstral-2-2512-free`
- **Empfehlung**: Definitiv hinzufügen - kostenlos und sehr starkes Wachstum

#### gpt-oss-120b - OpenAI
- **Token-Nutzung**: 344 Mrd. Tokens
- **Wachstum**: ↑61%
- **OpenRouter-Name**: `openai/gpt-oss-120b` (falls verfügbar)
- **Empfehlung**: Hinzufügen, wenn über OpenRouter verfügbar

#### DeepSeek V3.2 - DeepSeek
- **Token-Nutzung**: 154 Mrd. Tokens
- **Wachstum**: ↑40%
- **OpenRouter-Name**: `deepseek/deepseek-v3.2`
- **Empfehlung**: Hinzufügen

### 2. Neue Modelle (Priorität: HOCH)

#### GPT-5.2 - OpenAI
- **Token-Nutzung**: 113 Mrd. Tokens
- **Status**: Neu
- **OpenRouter-Name**: `openai/gpt-5.2`
- **Empfehlung**: Definitiv hinzufügen - neuestes OpenAI-Modell

### 3. Modelle mit hoher Nutzung und Wachstum (Priorität: MITTEL)

#### Gemini 2.5 Flash - Google
- **Token-Nutzung**: 449 Mrd. Tokens (2. Platz!)
- **Wachstum**: ↑2%
- **OpenRouter-Name**: `google/gemini-2.5-flash`
- **Empfehlung**: Hinzufügen, ersetzt `gemini-2.0-flash-exp`

#### Claude Haiku 4.5 - Anthropic
- **Token-Nutzung**: 101 Mrd. Tokens
- **Wachstum**: ↑10%
- **OpenRouter-Name**: `anthropic/claude-haiku-4.5`
- **Empfehlung**: Hinzufügen, ersetzt `claude-3-haiku`

#### Grok 4.1 Fast - x-ai
- **Token-Nutzung**: 139 Mrd. Tokens
- **Wachstum**: ↑13%
- **OpenRouter-Name**: `x-ai/grok-4.1-fast`
- **Empfehlung**: Hinzufügen

#### KAT-Coder-Pro V1 (free) - kwaipilot
- **Token-Nutzung**: 94,5 Mrd. Tokens
- **Wachstum**: ↑11%
- **Besonderheit**: Kostenlos verfügbar
- **OpenRouter-Name**: `kwaipilot/kat-coder-pro-v1-free` (falls verfügbar)
- **Empfehlung**: Prüfen und hinzufügen, wenn verfügbar

### 4. Modelle mit hoher Nutzung trotz Rückgang (Priorität: MITTEL)

#### Claude Sonnet 4.5 - Anthropic
- **Token-Nutzung**: 413 Mrd. Tokens (3. Platz!)
- **Wachstum**: ↓9% (aber immer noch sehr hohe absolute Nutzung)
- **OpenRouter-Name**: `anthropic/claude-sonnet-4.5`
- **Empfehlung**: Hinzufügen, ersetzt `claude-3-sonnet` (trotz Rückgang noch sehr relevant)

#### Claude Opus 4.5 - Anthropic
- **Token-Nutzung**: 197 Mrd. Tokens
- **Wachstum**: ↓15%
- **OpenRouter-Name**: `anthropic/claude-opus-4.5`
- **Empfehlung**: Hinzufügen, ersetzt `claude-3-opus` (trotz Rückgang noch relevant)

## Empfehlungen: Modelle entfernen/ersetzen

### 1. Veraltete Claude-Modelle (durch 4.5-Versionen ersetzen)
- ❌ `anthropic/claude-3-opus` → ✅ `anthropic/claude-opus-4.5`
- ❌ `anthropic/claude-3-sonnet` → ✅ `anthropic/claude-sonnet-4.5`
- ❌ `anthropic/claude-3-haiku` → ✅ `anthropic/claude-haiku-4.5`

### 2. Veraltete Gemini-Modelle
- ❌ `google/gemini-2.0-flash-exp` → ✅ `google/gemini-2.5-flash`

### 3. Veraltete GPT-Modelle (OpenAI direkt)
- ❌ `gpt-4.1` → ✅ `gpt-5.2` (falls verfügbar direkt über OpenAI)
- ❌ `gpt-4.1-mini` → ✅ `gpt-5.2` oder behalten für Mini-Varianten

### 4. Modelle mit starkem Rückgang (optional entfernen)
- `google/gemini-2.5-pro` (↓14%) - nicht in aktueller Config
- `minimax/m2` (↓13%) - nicht in aktueller Config
- `google/gemini-3-pro-preview` (↓13%) - nicht in aktueller Config

## Aktionsplan

1. **Sofort hinzufügen** (hohe Priorität):
   - `openai/gpt-5.2`
   - `mistralai/devstral-2-2512-free`
   - `google/gemini-2.5-flash`
   - `anthropic/claude-sonnet-4.5`
   - `anthropic/claude-opus-4.5`
   - `anthropic/claude-haiku-4.5`

2. **Hinzufügen** (mittlere Priorität):
   - `deepseek/deepseek-v3.2`
   - `x-ai/grok-4.1-fast`
   - `openai/gpt-oss-120b` (falls verfügbar)

3. **Ersetzen**:
   - Claude-3-Modelle durch Claude-4.5-Modelle
   - Gemini-2.0 durch Gemini-2.5

4. **Behalten** (weiterhin relevant):
   - `openai/gpt-4o` (stabil, hohe Nutzung)
   - `mistralai/mistral-medium-3.1` (aktuell als Standard verwendet)
   - `mistralai/mistral-large-latest`
   - `openai/gpt-4-turbo`
   - `meta-llama/llama-3-70b-instruct`

## OSS-Modelle für deutsche Texttransformation (Priorität: SEHR HOCH)

**WICHTIGE ERKENNTNIS:** Die Top-Modelle für deutsche Sprache auf OpenRouter sind überwiegend OSS-Modelle!

### Top-Modelle für Deutsch (basierend auf OpenRouter-Statistiken)

#### 1. Nemotron Nano 12B 2 VL - Nvidia
- **Deutsche Nutzung**: 34,2% (Platz 1!)
- **Besonderheit**: Potenziell Open-Weight/OSS, sehr dominant für Deutsch
- **OpenRouter-Name**: `nvidia/nemotron-nano-12b-2-vl` (oder ähnlich)
- **Empfehlung**: **DEFINITIV hinzufügen** - mit Abstand das meistgenutzte Modell für Deutsch
- **Lizenz**: Bitte prüfen, ob vollständig OSS-kompatibel

#### 2. Olmo 3 32B Think - AllenAI
- **Deutsche Nutzung**: 13,0% (Platz 2!)
- **Besonderheit**: AllenAI ist bekannt für Open Science und Open Models
- **OpenRouter-Name**: `allenai/olmo-3-32b-think` (oder ähnlich)
- **Empfehlung**: **DEFINITIV hinzufügen** - starker OSS-Kandidat, zweithöchste Nutzung für Deutsch
- **Lizenz**: Wahrscheinlich Apache 2.0 oder ähnlich (AllenAI-Modelle sind meist OSS)

#### 3. gpt-oss-20b - OpenAI
- **Deutsche Nutzung**: 4,8% (Platz 3)
- **Besonderheit**: Explizit als OSS gekennzeichnet
- **OpenRouter-Name**: `openai/gpt-oss-20b`
- **Empfehlung**: **Hinzufügen** - bereits in Ollama als `gpt-oss:20b` vorhanden, auch für OpenRouter relevant

#### 4. gpt-oss-120b - OpenAI
- **Deutsche Nutzung**: 4,7% (Platz 4)
- **Besonderheit**: Explizit als OSS gekennzeichnet, sehr großes Modell
- **OpenRouter-Name**: `openai/gpt-oss-120b`
- **Empfehlung**: **Hinzufügen** - bereits empfohlen, jetzt zusätzlich für Deutsch bestätigt

### Zusammenfassung für deutsche Texttransformation

**Die Top 4 Modelle für deutsche Sprache sind alle OSS-Modelle oder potenziell OSS!**

- **Gesamtanteil der Top 4 OSS-Modelle**: ~57% der deutschen Nutzung
- **Empfehlung**: Diese Modelle sollten **Priorität** für deutsche Texttransformation haben
- **Besonders wichtig**: Nemotron Nano und Olmo 3 sollten unbedingt getestet werden

### Weitere OSS-Modelle für Deutsch

- **Meta Llama 3 70B**: Bereits in Config vorhanden (`meta-llama/llama-3-70b-instruct`)
- **Mistral-Modelle**: Bereits vorhanden, Mistral ist bekannt für OSS-Modelle
- **Devstral 2 2512 (free)**: Bereits hinzugefügt, kostenlos und OSS

## Hinweise

- Die genauen Modellnamen in OpenRouter können leicht abweichen. Bitte vor dem Hinzufügen prüfen, ob die Namen korrekt sind.
- Free-Modelle wie `devstral-2-2512-free` sind besonders interessant für Entwicklung und Tests.
- Modelle mit Rückgang sollten nicht sofort entfernt werden, wenn sie noch hohe absolute Nutzung haben - sie könnten für spezifische Use-Cases weiterhin relevant sein.
- **Für deutsche Texttransformation**: OSS-Modelle zeigen deutlich bessere Nutzungsstatistiken als proprietäre Modelle - dies ist ein starkes Signal für deren Qualität im deutschen Sprachraum.
