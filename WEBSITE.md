# Sovereign Demo-Webseite

Dieses Paket enthält eine kleine Webseite, die direkt vom Sovereign-Server ausgeliefert wird.

## Start mit Docker

```powershell
docker compose down --remove-orphans --volumes
docker compose build --no-cache
docker compose up
```

Danach öffnen:

```text
http://localhost:8080/
```

## Enthaltene Routen

| Route | Zweck |
| --- | --- |
| `/` | HTML-Startseite |
| `/static/site.css` | Stylesheet |
| `/static/site.js` | Frontend-JavaScript |
| `/api/status` | Runtime-/Sandbox-Status als JSON |
| `/api/contact` | Validierte POST-Demo |
| `/healthz` | Docker Healthcheck |
| `/openapi.json` | OpenAPI-Skelett |

## POST-Demo

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8080/api/contact `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"name":"Ada","message":"Hallo Sovereign"}'
```

Die Route nutzt `@validate_body(ContactMessage)` und zeigt damit die eingebaute typensichere Request-Validierung.
