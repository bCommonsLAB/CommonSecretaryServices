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
- **Required**: Yes (for production)
- **Description**: API key for authenticating API requests
- **Example**: `your-secret-api-key`

## Optional Variables

### `MISTRAL_API_KEY`

- **Type**: String
- **Required**: No (only for Mistral OCR)
- **Description**: Mistral API key for OCR processing
- **Example**: `mistral-...`

### `ALLOW_LOCALHOST_NO_AUTH`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `false`
- **Description**: Allow localhost access without authentication (development only)
- **Example**: `true` or `1`

### `ALLOW_SWAGGER_WHITELIST`

- **Type**: String (comma/semicolon/space-separated IPs)
- **Default**: Empty
- **Description**: IP addresses or CIDR ranges allowed to access Swagger UI without authentication
- **Example**: `192.168.1.0/24,10.0.0.1` or `192.168.1.0/24;10.0.0.1`

### `AUTH_LOG_DECISIONS`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `false`
- **Description**: Log authentication decisions for debugging
- **Example**: `true` or `1`

### `PYTHONHTTPSVERIFY`

- **Type**: Boolean/String (`true`, `false`, `1`, `0`)
- **Default**: `true`
- **Description**: Disable SSL certificate verification (Windows workaround)
- **Example**: `0` or `false` (not recommended for production)

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
ALLOW_LOCALHOST_NO_AUTH=true
ALLOW_SWAGGER_WHITELIST=192.168.1.0/24
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
      - ALLOW_LOCALHOST_NO_AUTH=true
```

## Security Considerations

### API Key Security

- **Never commit API keys** to version control
- Use `.env` file (not tracked in git)
- Use environment variables in production
- Rotate API keys regularly

### Authentication

- **Production**: Always set `SECRETARY_SERVICE_API_KEY`
- **Development**: Can use `ALLOW_LOCALHOST_NO_AUTH=true` for local testing
- **Swagger UI**: Use `ALLOW_SWAGGER_WHITELIST` to restrict access

### SSL/TLS

- **Production**: Keep `PYTHONHTTPSVERIFY=1` (default)
- **Development**: Can disable for testing (`PYTHONHTTPSVERIFY=0`)

## Related Documentation

- [Configuration Reference](configuration.md) - Configuration file options
- [Security Guide](../../ops/security.md) - Security best practices

