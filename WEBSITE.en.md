# Sovereign Demo Website

This package contains a small website served directly from the Sovereign server.

## Start with Docker

```powershell
docker compose down --remove-orphans --volumes
docker compose build --no-cache
docker compose up
```

Then open:

```text
http://localhost:8080/
```

## Included Routes

| Route | Purpose |
| --- | --- |
| / | Homepage |
| Static Site CSS | Stylesheet |
| Frontend JavaScript | Frontend-JavaScript |
| /api/status (English) | Runtime-/Sandbox-Status as JSON |
| /api/contact | Validated POST Demo |
| /healthz | Docker Healthcheck |
| /openapi.json | OpenAPI Skeleton |

## POST Demo

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8080/api/contact `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"name":"Ada","message":"Hallo Sovereign"}'
```

The route uses `@validate_body(ContactMessage)` and demonstrates the built-in type-safe request validation.
