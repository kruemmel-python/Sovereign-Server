import dataclasses
import gzip
import time
import uuid

from sovereign import (
    GZipMiddleware,
    Inject,
    JSONResponse,
    JWTAuth,
    Response,
    Router,
    SQLiteJWTBlocklist,
    SovereignTestClient,
    rate_limit,
    request_scoped,
    singleton,
    validate_body,
    validate_query,
)
from sovereign.server import send_headers
from sovereign.config import DEFAULT_CONFIG
from sovereign.errors import HTTPError


@dataclasses.dataclass
class UserCreate:
    name: str
    age: int = 0


@dataclasses.dataclass
class PageQuery:
    page: int = 1
    active: bool = True


def test_validation_and_openapi():
    router = Router()

    @router.route("/users/{id}", methods=("POST",))
    @validate_query(PageQuery)
    @validate_body(UserCreate)
    def create(req):
        return JSONResponse({
            "id": req.route_params["id"],
            "name": req.validated_data.name,
            "age_type": type(req.validated_data.age).__name__,
            "page": req.validated_query.page,
            "active": req.validated_query.active,
        })

    client = SovereignTestClient(router)
    ok = client.post("/users/abc?page=2&active=false", json_body={"name": "Ada", "age": "37"})
    assert ok.status_code == 200
    assert ok.json()["age_type"] == "int"
    assert ok.json()["page"] == 2
    assert ok.json()["active"] is False

    bad = client.post("/users/abc", json_body={"name": "Ada", "unknown": 1})
    assert bad.status_code == 400

    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/users/{id}"]["post"]
    assert op["requestBody"]["content"]["application/json"]["schema"]["properties"]["age"]["type"] == "integer"
    assert any(p["name"] == "page" and p["in"] == "query" for p in op["parameters"])


def test_dependency_scopes():
    router = Router()
    calls = {"request": 0, "singleton": 0}

    @request_scoped
    def per_request():
        calls["request"] += 1
        return object()

    @singleton
    def app_singleton():
        calls["singleton"] += 1
        return object()

    def service(a=Inject(per_request)):
        return a

    @router.route("/di")
    def endpoint(req, a=Inject(per_request), b=Inject(service), s=Inject(app_singleton)):
        assert a is b
        return JSONResponse({"request": calls["request"], "singleton": calls["singleton"]})

    client = SovereignTestClient(router)
    assert client.get("/di").json() == {"request": 1, "singleton": 1}
    assert client.get("/di").json() == {"request": 2, "singleton": 1}


def test_gzip_middleware_and_rate_limit_headers():
    router = Router()
    router.middleware(GZipMiddleware(min_size=10))
    router.middleware(rate_limit(1, 60))

    @router.route("/big")
    def big(req):
        return JSONResponse({"payload": "x" * 100})

    client = SovereignTestClient(router)
    first = client.get("/big", headers={"Accept-Encoding": "gzip"})
    assert first.status_code == 200
    assert first.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(first.content).startswith(b'{"payload"')
    assert first.headers["X-RateLimit-Limit"] == "1"

    second = client.get("/big")
    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_jwt_revocation_sqlite(tmp_path):
    blocklist = SQLiteJWTBlocklist(tmp_path / "tokens.sqlite3")
    jwt = JWTAuth("secret", blocklist=blocklist)
    token = jwt.create_token({"sub": "u1"}, exp_seconds=60)
    payload = jwt.verify_token(token)
    assert payload["sub"] == "u1"
    assert payload["jti"]

    jwt.revoke_token(token, "logout")
    try:
        jwt.verify_token(token)
    except HTTPError as exc:
        assert exc.status == 401
        assert "revoked" in exc.message.lower()
    else:
        raise AssertionError("revoked token was accepted")


def test_fail_closed_header_injection():
    class DummySock:
        def __init__(self):
            self.data = b""
        def sendall(self, data):
            self.data += data

    try:
        send_headers(DummySock(), DEFAULT_CONFIG, 200, {"X-Bad": "ok\r\nInjected: yes"}, False)
    except HTTPError as exc:
        assert exc.status == 500
    else:
        raise AssertionError("CR/LF header injection was not rejected")
