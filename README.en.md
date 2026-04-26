# Sovereign Server V10 Professional

Minimalist Python HTTP/1.1 Framework and Server using only the Python standard library.

## V10 Add-ons

- **Paranoid Docker Sandbox**: non-root, read-only rootfs, dropped capabilities, no-new-privileges, seccomp profile, PID/CPU/RAM limits, and tmpfs-only writable paths.
- **Async-Middleware Pipeline without Nested Event Loops**: `Router.execute_async()` no longer uses the `asyncio.run()` bridge. Sync-middlewares are explicitly promoted into the awaitable chain.
- **Runtime Sandbox Diagnostics**: `SandboxPolicy`, `validate_runtime_environment()`, and dependency-free Docker Healthcheck helper.

## Paranoid Docker Start

```bash
docker compose build
docker compose up
```

More details available in `SANDBOX.md`.

## V7 Add-ons

- **In-Memory TestClient** for unit tests without TCP sockets.
- **Dependency Injection** with `Inject(provider)` in handler signatures.
- **Standard Middlewares**: CORS and CSRF protection.
- **Native async/await Handler** over secure coroutine detection.
- **Persistent Background Tasks** using SQLite Queue with retry logic.
- **WebSocket Head-of-Line Blocking Protection** via per-session send queues with limits.
- **Absolute Request-Timeouts** in addition to Idle-Timeouts.
- **JWT Hardening**: `kid` Key Rotation, strict algorithm validation, token length limit, `iss`/`aud`.

## Start

```bash
python -m examples.app --host 127.0.0.1 --port 8080
```

Or:

```bash
python -m sovereign.cli
```

## Tests

```bash
python -m unittest discover -s tests
```

## Example: TestClient

```python
from examples.app import router, jwt
from sovereign.testing import SovereignTestClient

client = SovereignTestClient(router)
token = jwt.create_token({"sub": "tester"})
resp = client.get("/users", headers={"authorization": f"Bearer {token}"})
assert resp.status_code == 200
```

## Security Warning

This package is dependency-minimal and auditable, but external security reviews, fuzzing, load testing, and OS-level hardening are required before direct internet operation.

## Sovereign v8 Extensions

This build includes the requested production hardening and framework extensions:

- Request validation via `validate_body()` and `validate_query()` using dataclasses/typing.
- Automatic OpenAPI skeleton at `GET /openapi.json` and `GET /docs`.
- Dependency injection lifecycles: `transient`, `request_scoped`/`scoped`, and `singleton`.
- Transparent `GZipMiddleware` and `CompressionMiddleware` for gzip/deflate responses, including static responses when routed through the server.
- Token-bucket rate limiting via `rate_limit()` with in-memory or SQLite storage.
- WebSocket presence tracking, typed event broadcasting, user session lookup, and active ping/pong heartbeat shutdown.
- Fail-closed response header validation against CRLF injection.
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

## This package includes eight additional production-oriented modules:

This package includes eight additional production-oriented modules:

- `AsyncSovereignServer`: asyncio-native HTTP/1.1 mode with direct awaiting of async route handlers and `asyncio.to_thread()` isolation for sync handlers.
- `EventHub`: unified WebSocket/SSE room, user, and presence hub. `hub.sse("room")` returns an `SSEResponse`; WebSockets and SSE receive the same broadcasts.
- sovereign.orm: dependency-free dataclass SQLite ORM with `Model`, `SQLiteORM.insert/save/get/query`.
- `sovereign.acme`: ACME HTTP-01 challenge installer, challenge storage, OpenSSL key/CSR helpers, and certificate-manager scaffolding for dependency-free Let's Encrypt integration.
- `sovereign.template`: Tiny auto-escaping template engine with `TemplateResponse`; values must be explicitly marked with `safe()` to bypass escaping.
- `sovereign.crypto`: Secure password hashing via `hashlib.scrypt`, random salts, and timing-safe verification.
- `sovereign.multipart`: Bounded multipart parser with strict part/file/file-size limits and magic-byte MIME checks.
- `bruteforce_protect`: SQLite-backed adaptive tarpit/fail2ban middleware for login endpoints.

All additions use only the Python standard library and are exported from `sovereign.__init__`.

## v10.1 Distroless production image

Use `Dockerfile.distroless` and `compose.distroless.yaml` for a shell-less, package-manager-less production runtime. See `DISTROLESS.md`.

## Demo Website

Start the container with `docker compose up --build` and open `http://localhost:8080/` afterward. Details are in `WEBSITE.md`.

## HTML5 Runtime

v10.5 can deliver complete HTML5 frontends from the `web/` directory: `/assets/...`, SPA fallback, ETags, Range Requests, gzip, PWA manifest, and strict browser security headers. See `HTML5.md`.
