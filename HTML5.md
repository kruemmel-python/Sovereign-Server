# Sovereign HTML5 Runtime

Sovereign kann ab v10.5 nicht nur Python-APIs, sondern komplette HTML5-Frontends ausliefern.

## Features

- HTML5-Dateien aus `web/`
- `/assets/...` für CSS, JavaScript, SVG, Manifest, WASM und Fonts
- SPA-Fallback für Deep Links wie `/dashboard/settings`
- `ETag`, `Last-Modified`, `Accept-Ranges` und Range Requests
- Gzip-Kompression für Textassets
- Asset-Manifest unter `/__assets.json`
- Strikte Browser-Security-Header inklusive CSP
- Docker-ready via `SOVEREIGN_WEB_DIR=/app/web`

## Nutzung

```python
from pathlib import Path
from sovereign import Router, HTML5App

router = Router()

# API-Routen zuerst registrieren.
# Danach HTML5App mounten, weil sie eine Catch-all Route nutzt.
HTML5App(
    root=Path("web"),
    assets_prefix="/assets",
    spa_fallback=True,
).mount(router)
```

## Docker

```powershell
docker compose down --remove-orphans --volumes
docker compose build --no-cache
docker compose up
```

Dann öffnen:

```text
http://localhost:8080/
```

## Paranoid Defaults

Die Demo nutzt keine Inline-Skripte. Dadurch kann die Content-Security-Policy streng bleiben:

```text
script-src 'self'
style-src 'self'
object-src 'none'
frame-ancestors 'none'
```

Für externe CDNs oder Inline-Code muss die CSP bewusst erweitert werden.
