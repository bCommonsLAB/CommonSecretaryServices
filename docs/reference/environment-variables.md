# Environment Variables

Complete documentation of all environment variables required for Common Secretary Services.

## Required Variables

### `OPENAI_API_KEY`

- **Type**: String
- **Required**: Yes (for LLM features)
- **Description**: OpenAI API key for GPT models and Whisper transcription
- **Example**: `sk-proj-...`

### `MONGODB_URI`

- **Type**: String (MongoDB URI)
- **Required**: Yes
- **Description**: MongoDB connection URI
- **Example**: `mongodb://localhost:27017/` or `mongodb://user:pass@host:27017/dbname`

### `SECRETARY_SERVICE_API_KEY`

- **Type**: String
- **Required**: Yes. The server refuses to start without it; protected routes answer 503 if it is missing at runtime.
- **Description**: API key for authenticating API requests (`Authorization: Bearer …` or `X-Secretary-Api-Key: …`)
- **Recommendation**: at least 32 characters, e.g. `openssl rand -hex 32`
- **Example**: `your-secret-api-key`

### `FLASK_SECRET_KEY`

- **Type**: String (at least 32 characters)
- **Required**: Yes, as soon as the dashboard uses a sign-in mode
- **Description**: Signs the dashboard session and CSRF tokens. One random value per installation.
- **Example**: output of `openssl rand -hex 32`

## MongoDB of the bundled compose file

### `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD`, `MONGO_DB_NAME`

- **Required**: `MONGO_ROOT_USER` and `MONGO_ROOT_PASSWORD` for `docker compose up`; compose refuses to start without them
- **Description**: Admin account of the bundled MongoDB (started with `--auth`, no host port). The compose file builds `MONGODB_URI` for the service from them. `MONGO_DB_NAME` defaults to `commonsec`. Use a password of letters and digits only, e.g. `openssl rand -hex 24`. Existing data volumes: [MongoDB-Migration](../deployment/mongo-migration.md)

## Dashboard sign-in

The web dashboard (`/`, `/logs`, `/llm-config`, `/docs`, Swagger) has its own sign-in. Without configuration it is **locked** (503 with a hint page). Guide: [Dashboard-Anmeldung](../deployment/dashboard-anmeldung.md).

### `DASHBOARD_AUTH_MODE`

- **Values**: `oidc`, `basic`, `forward`, `off`
- **Default**: derived — `oidc` if `OIDC_*` is set, `basic` if `DASHBOARD_USER` is set, otherwise locked
- `off` only works together with `ALLOW_INSECURE_NO_AUTH=true`; `forward` only with `TRUSTED_PROXY_COUNT` > 0

### `OIDC_ISSUER`, `OIDC_DISCOVERY_URL`

- **Required**: for `oidc` (one of both)
- **Description**: Base URL of the Nextcloud (`OIDC_ISSUER`) or the full URL of its `openid-configuration` document, if it is not at `<issuer>/.well-known/openid-configuration`

### `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`

- **Required**: for `oidc`
- **Description**: Client created in Nextcloud (app "OIDC Identity Provider")

### `PUBLIC_BASE_URL`

- **Required**: for `oidc`
- **Description**: Public address of this installation. The callback URL is `PUBLIC_BASE_URL/auth/callback` and must be registered in Nextcloud. Must start with `https://` (plain `http` only for localhost). Never derived from the `Host` header.

### `DASHBOARD_REQUIRED_GROUP`, `DASHBOARD_ALLOWED_USERS`

- **Required**: for `oidc`, at least one of both
- **Description**: Group that may use the dashboard (claim from `OIDC_GROUPS_CLAIM`, default `groups`), or a comma-separated list of user names / e-mail addresses

### `OIDC_GROUPS_CLAIM`, `OIDC_SCOPES`, `DASHBOARD_SESSION_HOURS`

- **Optional**: claim name for groups (default `groups`), scopes (default `openid profile email`, plus `groups` if offered), session lifetime in hours (default `12`)

### `DASHBOARD_USER`, `DASHBOARD_PASSWORD_HASH`

- **Required**: for `basic`
- **Description**: Emergency or local sign-in via HTTP Basic Auth. Create it with `python -m src.dashboard.auth hash-password`, which prints a ready line in dot notation (`pbkdf2:sha256:<iterations>.<salt>.<hash>`, no `$`, no quotes needed). The classic Werkzeug form with `$` is accepted too, also quoted or with `$$`. An invalid hash locks the dashboard with a log message; the API keeps running.

### `DASHBOARD_FORWARD_USER_HEADER`, `DASHBOARD_FORWARD_GROUPS_HEADER`, `DASHBOARD_LOGOUT_URL`

- **Optional**: only for `forward` behind an own authenticating proxy (defaults `X-Auth-Request-User`, `X-Auth-Request-Groups`)

### `TRUSTED_PROXY_COUNT`

- **Default**: `0`
- **Description**: Number of trusted reverse proxies in front of the service. With `0`, `X-Forwarded-*` headers are ignored. Set to `1` behind Traefik/Dokploy so the real client address is used for logs and the Swagger whitelist.

### `ALLOW_INSECURE_NO_AUTH`

- **Default**: `false`
- **Description**: Explicitly allows running without API token and without dashboard sign-in. Local development only.

## Optional Variables

### `MISTRAL_API_KEY`

- **Type**: String
- **Required**: No (only for Mistral OCR)
- **Description**: Mistral API key for OCR processing
- **Example**: `mistral-...`

### `VOYAGE_API_KEY`

- **Type**: String
- **Required**: No (only for RAG embedding features)
- **Description**: Voyage AI API key for text embedding generation
- **Example**: `pa-...`

### `ALLOW_LOCALHOST_NO_AUTH`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `false`
- **Description**: Allow API requests from loopback peers (`127.0.0.0/8`, `::1`) without token (development only). Only the real peer address counts; `Host` and forwarding headers are ignored.
- **Example**: `true` or `1`

### `SWAGGER_IP_WHITELIST` (formerly `ALLOW_SWAGGER_WHITELIST`)

- **Type**: String (comma/semicolon/space-separated IPs or CIDR networks)
- **Default**: Empty
- **Description**: Addresses that may open Swagger (`/api/doc`, `/api/swagger.json`) without sign-in. Does not open any other endpoint. The old name still works but is deprecated.
- **Example**: `192.168.1.0/24,10.0.0.1` or `192.168.1.0/24;2001:db8::/32`

### `AUTH_LOG_DECISIONS`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `false`
- **Description**: Log authentication decisions for debugging
- **Example**: `true` or `1`

### `PYTHONHTTPSVERIFY`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `true`
- **Description**: Disable TLS certificate verification for outgoing connections (Windows/corporate-proxy workaround). Takes effect **only together with `FLASK_ENV=development`**; otherwise the value is ignored, verification stays on and the start log prints a warning.
- **Example**: `0` or `false` (local development only)
- **Better alternative**: point `SSL_CERT_FILE` (and `REQUESTS_CA_BUNDLE`) to a CA bundle that contains the proxy certificate, e.g. the output of `python -c "import certifi; print(certifi.where())"` extended with your proxy CA.

### `YTDLP_COOKIES_FILE`

- **Type**: String (file path)
- **Default**: Empty
- **Description**: Path to cookies file for yt-dlp (for YouTube videos requiring authentication)
- **Example**: `/path/to/cookies.txt`

## Environment File (.env)

Create a `.env` file in the project root:

```bash
# Required
OPENAI_API_KEY=sk-proj-your-key-here
MONGODB_URI=mongodb://localhost:27017/
SECRETARY_SERVICE_API_KEY=your-secret-api-key

# Optional
MISTRAL_API_KEY=mistral-your-key-here
VOYAGE_API_KEY=pa-your-voyage-key-here
FLASK_SECRET_KEY=random-value-per-installation
DASHBOARD_AUTH_MODE=basic
DASHBOARD_USER=admin
DASHBOARD_PASSWORD_HASH=pbkdf2:sha256:1000000.<salt>.<hash>
SWAGGER_IP_WHITELIST=192.168.1.0/24
AUTH_LOG_DECISIONS=false
PYTHONHTTPSVERIFY=1
YTDLP_COOKIES_FILE=/path/to/cookies.txt
```

## Docker Environment Variables

When using Docker, set environment variables in `docker-compose.yml`:

```yaml
services:
  secretary-services:
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - MONGODB_URI=mongodb://mongodb:27017/
      - SECRETARY_SERVICE_API_KEY=${SECRETARY_SERVICE_API_KEY}
      - VOYAGE_API_KEY=${VOYAGE_API_KEY}
      - FLASK_SECRET_KEY=${FLASK_SECRET_KEY:-}
      - DASHBOARD_AUTH_MODE=${DASHBOARD_AUTH_MODE:-}
      # ... see docker-compose.yml for the full list
```

## Security Considerations

### API Key Security

- **Never commit API keys** to version control
- Use `.env` file (not tracked in git)
- Use environment variables in production
- Rotate API keys regularly

### Authentication

- **Fail-closed**: without `SECRETARY_SERVICE_API_KEY` the server does not start; without dashboard sign-in the dashboard is locked
- **Development**: `ALLOW_LOCALHOST_NO_AUTH=true` or, for no sign-in at all, `ALLOW_INSECURE_NO_AUTH=true`
- **Swagger UI**: dashboard sign-in, API key or `SWAGGER_IP_WHITELIST`

### SSL/TLS

- **Production**: TLS verification is always on. `PYTHONHTTPSVERIFY=0` is ignored unless `FLASK_ENV=development` is also set.
- **Development**: Prefer `SSL_CERT_FILE` with a CA bundle over disabling verification.
- **Downloads** from request URLs (PDF, audio, images, Vimeo) use connect/read timeouts, a total duration limit and the processor's size limit, counted while streaming.

## Related Documentation

- [Configuration Reference](configuration.md) - Configuration file options
- [Security Guide](../../ops/security.md) - Security best practices

