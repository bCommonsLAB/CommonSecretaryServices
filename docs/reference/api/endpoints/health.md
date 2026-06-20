# Health API Endpoints

Lightweight **availability checks** for the LLM-backed operations. A client can
call these **before** invoking a processing endpoint to find out whether the
underlying operation is currently available (provider reachable, API key
configured, OpenRouter credit left).

These endpoints answer the question *"can this operation run right now?"* — they
do **not** measure load/throughput (overload handling is covered by separate
strategies).

!!! info "No authentication required"
    All `/api/health*` endpoints are **exempt from the service token** (see the
    auth middleware). They never return secrets (no API keys, no raw provider
    tracebacks).

## How resolution works

Each LLM operation is modelled as a **use-case** (e.g. `transcription`,
`chat_completion`). The active provider/model per use-case is resolved from
**MongoDB first** (`llm_use_case_config`), falling back to `config.yaml`. The
health check uses the exact same resolution path as the real processors, so it
can never disagree with what an actual request would use.

Several endpoints are **cascading** (one processor calls others). The
per-endpoint check therefore aggregates the *transitive* set of use-cases and
reports the **worst** sub-status.

### Endpoint → required use-cases (cascade)

| Endpoint | Required use-cases (transitive) |
|----------|---------------------------------|
| `transformer` | `chat_completion` |
| `audio` | `transcription`, `chat_completion` |
| `video` | `transcription`, `chat_completion` |
| `youtube` | `transcription`, `chat_completion` |
| `imageocr` | `image2text`, `chat_completion` |
| `pdf` | `ocr_pdf`, `image2text`, `chat_completion` |
| `metadata` / `story` / `track` / `event` | `chat_completion` |
| `session` | `transcription`, `ocr_pdf`, `image2text`, `chat_completion` |
| `text2image` | `text2image` |
| `image_analyzer` | `image_analysis` |
| `rag` | `embedding` |

## Status values

| Status | Meaning |
|--------|---------|
| `healthy` | Config OK, provider reachable (and, for OpenRouter, credit available). |
| `degraded` | Reachable, but OpenRouter credit is **low** (below the configured threshold, default 5 USD). |
| `unavailable` | Config broken (provider disabled / missing API key / not registered), **or** provider unreachable / invalid key, **or** OpenRouter credit exhausted. |
| `unknown` | Could not be determined (e.g. provider offers no cheap probe, or an internal error). |
| `no_llm_dependency` | The endpoint has no LLM dependency. |

Endpoint / overall status = the **worst** status among the relevant use-cases
(`unavailable` < `degraded` < `unknown` < `healthy`).

---

## GET /api/health/live

Liveness probe. Returns `200 OK` as long as the process is serving. No
dependencies are checked. Intended for container/orchestrator health checks
(Docker `HEALTHCHECK`, Kubernetes liveness).

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "alive",
  "service": "common-secretary-services",
  "timestamp": "2026-06-05T10:21:00.000000+00:00"
}
```

---

## GET /api/health/

Overview of **all** use-cases and (cascading) endpoints in a single call.

### Request Example

```bash
curl "http://localhost:5001/api/health/"
```

### Response (Success)

**Status Code**: `200 OK` (the HTTP code is always 200; read `status` from the body)

```json
{
  "status": "degraded",
  "checked_at": "2026-06-05T10:21:00.000000+00:00",
  "use_cases": {
    "chat_completion": {
      "use_case": "chat_completion",
      "provider": "openrouter",
      "model": "google/gemini-2.5-flash",
      "model_id": "openrouter/google/gemini-2.5-flash",
      "status": "healthy",
      "config_source": "mongodb",
      "checks": {
        "config": {
          "ok": true, "provider_registered": true, "enabled": true,
          "api_key_present": true, "model_in_catalog": true,
          "detail": "Provider konfiguriert, API-Key vorhanden."
        },
        "connectivity": { "reachable": true, "latency_ms": 142, "detail": "Key-Limit (/key)" },
        "credit": { "status": "ok", "remaining_usd": 74.75, "threshold_usd": 5.0, "detail": "Key-Limit (/key)" }
      },
      "detail": "Verfügbar.",
      "checked_at": "2026-06-05T10:21:00.000000+00:00"
    },
    "transcription": {
      "use_case": "transcription",
      "provider": "openai",
      "model": "gpt-4o-transcribe",
      "model_id": "openai/gpt-4o-transcribe",
      "status": "unavailable",
      "config_source": "mongodb",
      "checks": {
        "config": {
          "ok": false, "provider_registered": true, "enabled": true,
          "api_key_present": false, "model_in_catalog": true,
          "detail": "API-Key für Provider 'openai' fehlt (Umgebungsvariable nicht gesetzt)."
        }
      },
      "detail": "API-Key für Provider 'openai' fehlt (Umgebungsvariable nicht gesetzt).",
      "checked_at": "2026-06-05T10:21:00.000000+00:00"
    }
  },
  "endpoints": {
    "audio": {
      "endpoint": "audio",
      "status": "unavailable",
      "use_cases": [
        { "use_case": "transcription", "status": "unavailable", "provider": "openai", "model": "gpt-4o-transcribe" },
        { "use_case": "chat_completion", "status": "healthy", "provider": "openrouter", "model": "google/gemini-2.5-flash" }
      ]
    }
  }
}
```

---

## GET /api/health/use-case/{use_case}

Pre-flight check for a single use-case.

**Path parameter** `use_case` — one of: `chat_completion`, `transcription`,
`image2text`, `ocr_pdf`, `image_analysis`, `text2image`, `embedding`,
`transformer_xxl`.

### Request Example

```bash
curl "http://localhost:5001/api/health/use-case/ocr_pdf"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "use_case": "ocr_pdf",
  "provider": "mistral",
  "model": "mistral-ocr-2512",
  "model_id": "mistral/mistral-ocr-2512",
  "status": "healthy",
  "config_source": "mongodb",
  "checks": {
    "config": { "ok": true, "provider_registered": true, "enabled": true, "api_key_present": true, "model_in_catalog": true, "detail": "Provider konfiguriert, API-Key vorhanden." },
    "connectivity": { "reachable": true, "latency_ms": 88, "detail": "models.list ok" }
  },
  "detail": "Verfügbar.",
  "checked_at": "2026-06-05T10:21:00.000000+00:00"
}
```

### Response (Unknown use-case)

**Status Code**: `404 Not Found`

```json
{
  "status": "unknown",
  "error": "Unbekannter Use-Case 'foo'.",
  "valid_use_cases": ["transcription", "image2text", "ocr_pdf", "chat_completion", "embedding", "transformer_xxl", "text2image", "image_analysis"]
}
```

---

## GET /api/health/endpoint/{endpoint}

Pre-flight check for a (possibly cascading) endpoint. Aggregates the transitive
use-cases (see the cascade table above) and returns the worst status.

**Path parameter** `endpoint` — e.g. `audio`, `video`, `youtube`, `pdf`,
`imageocr`, `transformer`, `session`, `event`, `track`, `story`, `metadata`,
`text2image`, `image_analyzer`, `rag`.

### Request Example

```bash
curl "http://localhost:5001/api/health/endpoint/session"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "endpoint": "session",
  "status": "unavailable",
  "use_cases": [
    { "use_case": "transcription", "status": "unavailable", "provider": "openai", "model": "gpt-4o-transcribe", "config_source": "mongodb", "checks": { "...": "..." } },
    { "use_case": "ocr_pdf", "status": "healthy", "provider": "mistral", "model": "mistral-ocr-2512", "config_source": "mongodb", "checks": { "...": "..." } },
    { "use_case": "image2text", "status": "unavailable", "provider": "openai", "model": "gpt-4o", "config_source": "mongodb", "checks": { "...": "..." } },
    { "use_case": "chat_completion", "status": "healthy", "provider": "openrouter", "model": "google/gemini-2.5-flash", "config_source": "mongodb", "checks": { "...": "..." } }
  ],
  "checked_at": "2026-06-05T10:21:00.000000+00:00"
}
```

### Response (Unknown endpoint)

**Status Code**: `404 Not Found`

```json
{
  "endpoint": "foo",
  "status": "unknown",
  "detail": "Unbekannter Endpoint 'foo'. Bekannt: audio, event, image_analyzer, imageocr, metadata, pdf, rag, session, story, text2image, track, transformer, video, youtube",
  "use_cases": [],
  "checked_at": "2026-06-05T10:21:00.000000+00:00"
}
```

---

## Field reference

| Field | Description |
|-------|-------------|
| `status` | `healthy` / `degraded` / `unavailable` / `unknown` / `no_llm_dependency`. |
| `provider` / `model` | The resolved provider and model for the use-case. |
| `model_id` | Full id `{provider}/{model}` (matches the `llm_use_case_config` entry). |
| `config_source` | `mongodb`, `config_yaml`, `mongodb (stale: reload_config nötig)`, or `config_yaml (Fallback: MongoDB-Modell nicht im llm_models-Katalog)`. Use this to detect whether MongoDB config is actually in effect. |
| `checks.config` | Static checks: provider registered, enabled, API key present, model in catalog (informational). |
| `checks.connectivity` | `reachable` (`true`/`false`/`null`), `latency_ms`, `detail`. `null` = the provider offers no cheap probe (e.g. VoyageAI). |
| `checks.credit` | **OpenRouter only.** `status` (`ok`/`low`/`insufficient`/`unknown`), `remaining_usd`, `threshold_usd`. |

## Notes & limitations

- **Credit** is only available for **OpenRouter** (via `/api/v1/key`, falling
  back to `/api/v1/credits`). OpenAI, Mistral and VoyageAI expose no reliable
  balance endpoint — for them the check verifies config + reachability only;
  an exhausted balance there will only surface on a real call.
- **Connectivity** is provider-level (a `GET /models`-style probe). It validates
  the key and reachability, not that the specific model id exists.
- Results are **cached** for ~30s per use-case to avoid hammering providers on
  frequent polling. The cache is per process (per worker).
- `model_in_catalog` is **informational only** and never causes `unavailable`
  (the configured `available_models` in `config.yaml` may legitimately differ
  from the model selected via MongoDB).

## Recommended client usage

1. Before submitting a large/long job, call
   `GET /api/health/endpoint/<endpoint>`. If `status == "unavailable"`, do not
   submit; if `degraded`, submit but warn the user (e.g. low credit).
2. Use `GET /api/health/live` for container/orchestrator probes.
3. A green health check does not guarantee a real call succeeds — keep handling
   errors from the processing endpoints as well.
