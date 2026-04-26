# Sovereign HTML5 Runtime

Sovereign can, starting from v10.5, deliver not only Python APIs but complete HTML5 frontends.

## Features

- HTML5 files from the `web/` directory
- /assets/... for CSS, JavaScript, SVG, Manifest, WASM, and Fonts
- SPA fallback for deep links like /dashboard/settings
- ETag, Last-Modified, Accept-Ranges, and Range Requests
- Gzip compression for text assets
- Asset Manifest at `/__assets.json`
- Strict Browser Security Headers including CSP
- Docker-ready via `SOVEREIGN_WEB_DIR=/app/web`

## Usage

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

Then open:

```text
http://localhost:8080/
```

## Paranoid Defaults

This demo does not use inline scripts. This allows the Content Security Policy to remain strict:

```text
script-src 'self'
style-src 'self'
object-src 'none'
frame-ancestors 'none'
```

For external CDNs or inline code, the CSP must be intentionally expanded.
