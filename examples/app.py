from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import time

from sovereign import Router, JSONResponse, Inject, JWTAuth, require_auth, HTML5App
from sovereign.middleware import CORSMiddleware
from sovereign.validation import validate_body

router = Router()
router.middleware(CORSMiddleware(allow_origins=("*",)))

jwt = JWTAuth({"v1": "dev-secret-old", "v2": "dev-secret-current"}, current_kid="v2", issuer="sovereign-demo")


@dataclass
class ContactMessage:
    name: str
    message: str


def get_db():
    return {"users": ["Ada", "Grace"]}


def audit_log(message: str):
    print("AUDIT", message)


@router.on_startup
def startup(state: dict):
    state["started"] = True
    state["started_at"] = time.time()


@router.on_shutdown
def shutdown(state: dict):
    state["stopped"] = True


def _uptime_seconds(req) -> int:
    started_at = req.app_state.get("started_at", time.time())
    return max(0, int(time.time() - started_at))


@router.route("/api/status")
def api_status(req):
    return JSONResponse(
        {
            "ok": True,
            "service": "sovereign-server",
            "version": "10.5-html5",
            "html5": {
                "enabled": True,
                "spa_fallback": True,
                "asset_manifest": "/__assets.json",
                "assets": "/assets/",
            },
            "sandbox": os.environ.get("SOVEREIGN_SANDBOX", "unknown"),
            "python": platform.python_version(),
            "platform": platform.system().lower(),
            "uptime_seconds": _uptime_seconds(req),
            "request_id": req.request_id,
            "remote_addr": req.remote_addr,
        }
    )


@router.route("/api/contact", methods=("POST",))
@validate_body(ContactMessage)
def contact(req):
    data: ContactMessage = req.validated_data
    return JSONResponse(
        {
            "ok": True,
            "received": {
                "name": data.name,
                "message": data.message,
                "length": len(data.message),
            },
            "request_id": req.request_id,
        },
        status=201,
    )


@router.route("/healthz")
def healthz(req):
    return JSONResponse({"ok": True})


@router.route("/token")
def token(req):
    return JSONResponse({"token": jwt.create_token({"sub": "demo"})})


@router.route("/users", middlewares=(require_auth(jwt),))
def users(req, db=Inject(get_db)):
    return JSONResponse({"user": req.user, "users": db["users"]})


@router.route("/async")
async def async_route(req):
    return JSONResponse({"async": True})


@router.route("/task")
def task(req):
    req.add_background_task(audit_log, "non-persistent task")
    # Persistent tasks must be importable and JSON-serializable.
    req.add_background_task(audit_log, "persistent task", persistent=True)
    return JSONResponse({"queued": True})


# HTML5 frontend mount must come after API routes because it intentionally
# registers a catch-all route for deep links such as /dashboard/settings.
HTML5App(
    root=Path(os.environ.get("SOVEREIGN_WEB_DIR", "web")),
    prefix="/",
    assets_prefix="/assets",
    spa_fallback=True,
    security_headers=True,
    expose_manifest=True,
).mount(router)


if __name__ == "__main__":
    from sovereign.cli import main

    main(router)
