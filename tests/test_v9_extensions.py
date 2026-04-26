from __future__ import annotations

import dataclasses
import asyncio
from pathlib import Path

import pytest

from sovereign import (
    AsyncSovereignServer, EventHub, Model, SQLiteORM, Template, safe,
    hash_password, verify_password, parse_multipart, Request, DEFAULT_CONFIG,
    bruteforce_protect, Router, Response, SovereignTestClient, CertificateManager,
)
from sovereign.errors import HTTPError


def test_crypto_scrypt_hash_and_verify():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_template_autoescape_and_safe():
    tpl = Template("<p>{{ user }}</p><b>{{ html|safe }}</b><i>{{ trusted }}</i>")
    out = tpl.render({"user": "<Ada>", "html": safe("<em>x</em>"), "trusted": safe("<u>ok</u>")})
    assert "&lt;Ada&gt;" in out
    assert "<em>x</em>" in out
    assert "<u>ok</u>" in out


@dataclasses.dataclass
class User(Model):
    name: str = ""
    age: int = 0
    active: bool = True


def test_sqlite_orm_insert_query_save(tmp_path):
    db = SQLiteORM(tmp_path / "app.sqlite3")
    ada = db.insert(User(name="Ada", age=37))
    assert ada.id is not None
    assert db.get(User, ada.id).name == "Ada"
    ada.age = 38
    db.save(ada)
    assert db.query(User).where(active=True).first().age == 38


def test_eventhub_sse_broadcast():
    hub = EventHub()
    resp = hub.sse("room", user_id="u1")
    assert hub.is_online("u1")
    hub.broadcast_event("room", "notice", {"x": 1})
    first = next(iter(resp.chunks)).decode()
    assert "event: notice" in first
    assert '"x": 1' in first


def test_multipart_limits_and_magic_check():
    boundary = "BOUNDARY"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nhello\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG\r\n\x1a\nabc\r\n" + f"--{boundary}--\r\n".encode()
    headers = {"host": "x", "content-type": f"multipart/form-data; boundary={boundary}"}
    req = Request("POST", "/upload", "HTTP/1.1", headers, tuple(headers.items()), body, len(body), ("127.0.0.1", 1), DEFAULT_CONFIG)
    data = parse_multipart(req, max_files=1, max_file_size=64, max_parts=4)
    assert data.fields["title"] == "hello"
    assert data.files["file"].sniffed_type == "image/png"

    bad = body.replace(b"\x89PNG\r\n\x1a\n", b"#!/bin/s")
    req_bad = Request("POST", "/upload", "HTTP/1.1", headers, tuple(headers.items()), bad, len(bad), ("127.0.0.1", 1), DEFAULT_CONFIG)
    with pytest.raises(HTTPError):
        parse_multipart(req_bad)


def test_bruteforce_blocks_after_failures(tmp_path):
    router = Router()
    guard = bruteforce_protect(max_attempts=2, block_seconds=60, db_path=tmp_path / "bf.sqlite3", base_delay=1.0, max_delay=0.0)

    @router.route("/login", methods=("POST",), middlewares=(guard,))
    def login(req):
        raise HTTPError(401, "bad")

    c = SovereignTestClient(router)
    assert c.post("/login", json_body={"username": "ada"}).status_code == 401
    assert c.post("/login", json_body={"username": "ada"}).status_code == 401
    assert c.post("/login", json_body={"username": "ada"}).status_code == 403


def test_async_router_executes_async_handler():
    router = Router()

    @router.route("/async")
    async def hello(req):
        await asyncio.sleep(0)
        return Response("ok")

    async def run():
        req = Request("GET", "/async", "HTTP/1.1", {"host": "x"}, (("host", "x"),), b"", 0, ("127.0.0.1", 1), DEFAULT_CONFIG)
        handler, mw = await router.resolve_async("GET", "/async")
        return await router.execute_async(req, handler, mw)

    resp = asyncio.run(run())
    assert resp.body == b"ok"
    assert AsyncSovereignServer is not None


def test_acme_http01_route(tmp_path):
    router = Router()
    mgr = CertificateManager(router, domains=["example.com"], cert_dir=tmp_path).configure_router()
    mgr.add_challenge("token123", "token123.keyauth")
    client = SovereignTestClient(router)
    assert client.get("/.well-known/acme-challenge/token123").text == "token123.keyauth"
