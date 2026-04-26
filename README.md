# Sovereign Server V10 Professional

Dependency-minimal Python HTTP/1.1 framework/server using only the Python standard library.

## V10 Erweiterungen

1. **Paranoid Docker Sandbox**: non-root, read-only rootfs, dropped capabilities, no-new-privileges, seccomp profile, PID/CPU/RAM-Limits und tmpfs-only Schreibpfade.
2. **Async-Middleware-Pipeline ohne Nested Event-Loops**: `Router.execute_async()` nutzt keine `asyncio.run()`-Brücke mehr. Sync-Middlewares werden explizit in die Awaitable-Kette promoted.
3. **Runtime Sandbox Diagnostics**: `SandboxPolicy`, `validate_runtime_environment()` und dependency-free Docker Healthcheck-Helfer.

## Paranoid Docker Start

```bash
docker compose build
docker compose up
```

Weitere Details stehen in `SANDBOX.md`.

## V7 Erweiterungen

1. **In-Memory TestClient** für Unit-Tests ohne TCP-Socket.
2. **Dependency Injection** mit `Inject(provider)` in Handler-Signaturen.
3. **Standard-Middlewares**: CORS und CSRF.
4. **Native async/await Handler** über sichere Coroutine-Erkennung.
5. **Persistente Background-Tasks** über SQLite-Queue mit Retry-Logik.
6. **WebSocket Head-of-Line Blocking Schutz** durch per-Session Send-Queues mit Limits.
7. **Absolute Request-Timeouts** zusätzlich zu Idle-Timeouts.
8. **JWT-Härtung**: `kid` Key-Rotation, strikte Algorithmenprüfung, Token-Längenlimit, `iss`/`aud`.

## Start

```bash
python -m examples.app --host 127.0.0.1 --port 8080
```

Oder:

```bash
python -m sovereign.cli
```

## Tests

```bash
python -m unittest discover -s tests
```

## Beispiel: TestClient

```python
from examples.app import router, jwt
from sovereign.testing import SovereignTestClient

client = SovereignTestClient(router)
token = jwt.create_token({"sub": "tester"})
resp = client.get("/users", headers={"authorization": f"Bearer {token}"})
assert resp.status_code == 200
```

## Sicherheitshinweis

Das Paket ist dependency-minimal und auditierbar, aber vor direktem Internetbetrieb sind externe Security Reviews, Fuzzing, Lasttests und OS-Level-Härtung erforderlich.


## Sovereign v8 Extensions

This build includes the requested production hardening and framework extensions:

- Dataclass/typing request validation via `validate_body()` and `validate_query()`.
- Automatic OpenAPI skeleton at `GET /openapi.json` and `GET /docs`.
- Dependency injection lifecycles: `transient`, `request_scoped`/`scoped`, and `singleton`.
- Transparent `GZipMiddleware` and `CompressionMiddleware` for gzip/deflate responses, including static responses when routed through the server.
- Token-bucket rate limiting via `rate_limit()` with in-memory or SQLite storage.
- WebSocket presence tracking, typed event broadcasting, user session lookup, and active ping/pong heartbeat shutdown.
- Fail-closed response-header validation against CR/LF injection.
- JWT revocation using `SQLiteJWTBlocklist`, automatic `jti` issuance, and cleanup helpers for `SQLiteTaskQueue`.
- Strict TLS handshake timeout via `ServerConfig.tls_handshake_timeout`.

Minimal example:

```python
import dataclasses
from sovereign import Router, JSONResponse, validate_body, request_scoped, Inject, GZipMiddleware, rate_limit

@dataclasses.dataclass
class UserCreate:
    name: str
    age: int = 0

router = Router()
router.middleware(GZipMiddleware(min_size=512))
router.middleware(rate_limit(100, 60))

@request_scoped
def get_db():
    return object()

@router.route("/users", methods=("POST",))
@validate_body(UserCreate)
def create_user(req, db=Inject(get_db)):
    user = req.validated_data
    return JSONResponse({"name": user.name, "age": user.age})
```


## Sovereign v9 Professional Extensions

This package includes eight additional production-oriented modules:

- `AsyncSovereignServer`: asyncio-native HTTP/1.1 mode with direct awaiting of async route handlers and `asyncio.to_thread()` isolation for sync handlers.
- `EventHub`: unified WebSocket/SSE room, user and presence hub. `hub.sse("room")` returns an `SSEResponse`; WebSockets and SSE receive the same broadcasts.
- `sovereign.orm`: dependency-free dataclass SQLite ORM with `Model`, `SQLiteORM.insert/save/get/query`.
- `sovereign.acme`: ACME HTTP-01 route installer, challenge store, OpenSSL key/CSR helpers and certificate-manager scaffold for dependency-free Let's Encrypt integration.
- `sovereign.template`: tiny auto-escaping template engine plus `TemplateResponse`; values must be explicitly marked with `safe()` to bypass escaping.
- `sovereign.crypto`: secure password hashing via `hashlib.scrypt`, random salts and timing-safe verification.
- `sovereign.multipart`: bounded multipart parser with hard part/file/file-size limits and magic-byte MIME checks.
- `bruteforce_protect`: SQLite-backed adaptive tarpit/fail2ban middleware for login endpoints.

All additions use only the Python standard library and are exported from `sovereign.__init__`.


## v10.1 Distroless production image

Use `Dockerfile.distroless` and `compose.distroless.yaml` for a shell-less, package-manager-less production runtime. See `DISTROLESS.md`.


## Demo-Webseite

Starte den Container mit `docker compose up --build` und öffne anschließend `http://localhost:8080/`. Details stehen in `WEBSITE.md`.


## HTML5 Runtime

v10.5 kann komplette HTML5-Frontends aus `web/` ausliefern: `/assets/...`, SPA-Fallback, ETags, Range Requests, gzip, PWA-Manifest und strikte Browser-Security-Header. Siehe `HTML5.md`.
