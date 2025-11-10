# OpenAPI / Swagger Documentation

Interactive API documentation via Swagger UI.

## Accessing Swagger UI

The Swagger UI is available at:

- **Local**: `http://localhost:5001/api/doc`
- **Production**: `https://commonsecretaryservices.bcommonslab.org/api/doc`

## Features

- **Interactive API Explorer**: Test all endpoints directly from the browser
- **Request/Response Examples**: See example requests and responses for each endpoint
- **Authentication**: Enter your API key directly in the Swagger UI
- **Schema Documentation**: View detailed request/response schemas
- **Try It Out**: Execute API calls directly from the documentation

## Using Swagger UI

### 1. Access the Swagger UI

Navigate to `/api/doc` in your browser.

### 2. Authenticate

Click the "Authorize" button at the top of the page and enter your API key:
- **API Key**: Your `SECRETARY_SERVICE_API_KEY` value
- **Format**: Enter the key directly (no "Bearer" prefix needed)

### 3. Explore Endpoints

Browse endpoints by category:
- Audio Processing
- Video Processing
- PDF Processing
- ImageOCR
- Transformer
- Session Processing
- Event Processing
- Track Processing
- Story Generation
- Job Management

### 4. Test Endpoints

1. Click on an endpoint to expand it
2. Click "Try it out"
3. Fill in the required parameters
4. Click "Execute"
5. View the response

## OpenAPI Specification

The OpenAPI specification (Swagger JSON) is available at:

- `/api/swagger.json`

You can download this specification and use it with:
- Postman
- Insomnia
- Other API clients
- Code generation tools

### Downloading the Specification

```bash
curl -X GET "http://localhost:5001/api/swagger.json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o swagger.json
```

## Authentication in Swagger UI

Swagger UI supports two authentication methods:

1. **API Key Header**: `X-Secretary-Api-Key: <token>`
2. **Bearer Token**: `Authorization: Bearer <token>`

Both methods are configured in the Swagger UI authorization dialog.

## Exempt Paths

The following paths do not require authentication and can be accessed without an API key:
- `/api/doc` - Swagger UI itself
- `/api/swagger.json` - OpenAPI specification
- `/api/health` - Health check endpoints

## IP Whitelist

For Swagger UI access, you can configure an IP whitelist via the `ALLOW_SWAGGER_WHITELIST` environment variable:

```bash
ALLOW_SWAGGER_WHITELIST=192.168.1.0/24,10.0.0.1
```

This allows access to Swagger UI from specified IP addresses without authentication.

## Localhost Access

For local development, you can allow localhost access without authentication:

```bash
ALLOW_LOCALHOST_NO_AUTH=true
```

This allows access from `127.0.0.1` and `localhost` without an API key.

## Related Documentation

- [API Overview](overview.md) - Complete API endpoint overview
- [Endpoint Documentation](endpoints/) - Detailed endpoint documentation

