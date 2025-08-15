---
status: draft
last_verified: 2025-08-15
---

# OpenAPI / Swagger

- Swagger UI: `http://localhost:5000/api/doc`
- OpenAPI JSON: `http://localhost:5000/api/swagger.json`

## JSON abrufen
```bash
curl -s http://localhost:5000/api/swagger.json -o openapi.json
```

Die Swagger UI ist die primäre Referenz. Die JSON kann für externe Tools (z. B. SDK‑Generierung) genutzt werden.
