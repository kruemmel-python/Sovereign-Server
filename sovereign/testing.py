from __future__ import annotations
import json
from typing import Mapping, Optional
from .config import DEFAULT_CONFIG, ServerConfig
from .errors import HTTPError
from .request import Request
from .responses import Response, StreamResponse
from .router import Router

class TestResponse:
    def __init__(self, response: Response | StreamResponse) -> None:
        self.response = response
        self.status_code = response.status
        self.headers = response.headers
        if isinstance(response, StreamResponse):
            self.content = b"".join(response.chunks)
            self.text = self.content.decode("utf-8", errors="replace")
        else:
            self.content = response.body
            self.text = response.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content.decode("utf-8"))

class SovereignTestClient:
    def __init__(self, router: Router, config: ServerConfig = DEFAULT_CONFIG, app_state: Optional[dict] = None) -> None:
        self.router = router
        self.config = config
        self.app_state = app_state or {}

    def request(self, method: str, path: str, *, json_body=None, data: bytes | str | None = None,
                headers: Optional[Mapping[str, str]] = None) -> TestResponse:
        hdr = {k.lower(): v for k, v in (headers or {}).items()}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            hdr.setdefault("content-type", "application/json")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        else:
            body = b""
        hdr.setdefault("host", "testserver")
        req = Request(method.upper(), path, "HTTP/1.1", hdr, tuple(hdr.items()), body, len(body),
                      ("127.0.0.1", 50000), self.config, app_state=self.app_state)
        try:
            handler, mw = self.router.resolve(method.upper(), req.path)
            resp = self.router.execute(req, handler, mw)
        except HTTPError as err:
            resp = Response(err.message, status=err.status, headers=getattr(err, "headers", {}) or {})
        return TestResponse(resp)

    def get(self, path: str, **kw) -> TestResponse:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> TestResponse:
        return self.request("POST", path, **kw)

    def put(self, path: str, **kw) -> TestResponse:
        return self.request("PUT", path, **kw)

    def delete(self, path: str, **kw) -> TestResponse:
        return self.request("DELETE", path, **kw)
