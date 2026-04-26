from __future__ import annotations
import gzip, zlib, secrets
from typing import Callable, Iterable
from .errors import HTTPError
from .request import Request
from .responses import Response, StreamResponse

HandlerResult = Response | StreamResponse

class CORSMiddleware:
    def __init__(self, allow_origins: Iterable[str] = ("*",),
                 allow_methods: Iterable[str] = ("GET","POST","PUT","PATCH","DELETE","OPTIONS"),
                 allow_headers: Iterable[str] = ("Content-Type","Authorization","X-Request-Id","X-CSRF-Token"),
                 allow_credentials: bool = False, max_age: int = 86400) -> None:
        self.allow_origins = tuple(allow_origins)
        self.allow_methods = ", ".join(allow_methods)
        self.allow_headers = ", ".join(allow_headers)
        self.allow_credentials = allow_credentials
        self.max_age = str(max_age)

    def _origin(self, req: Request) -> str:
        origin = req.header("origin")
        if "*" in self.allow_origins:
            return "*" if not self.allow_credentials else origin
        return origin if origin in self.allow_origins else ""

    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        origin = self._origin(req)
        if req.method == "OPTIONS":
            resp = Response(b"", status=204)
        else:
            resp = call_next(req)
        if origin:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = self.allow_methods
            resp.headers["Access-Control-Allow-Headers"] = self.allow_headers
            resp.headers["Access-Control-Max-Age"] = self.max_age
            if self.allow_credentials:
                resp.headers["Access-Control-Allow-Credentials"] = "true"
        return resp

class CSRFMiddleware:
    SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}
    def __init__(self, cookie_name: str = "sovereign_csrf", header_name: str = "x-csrf-token") -> None:
        self.cookie_name = cookie_name
        self.header_name = header_name.lower()

    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        if req.method not in self.SAFE:
            cookie = req.cookies.get(self.cookie_name)
            header = req.header(self.header_name)
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                raise HTTPError(403, "CSRF validation failed")
        resp = call_next(req)
        if self.cookie_name not in req.cookies:
            token = secrets.token_urlsafe(32)
            resp.headers.setdefault("Set-Cookie", f"{self.cookie_name}={token}; Path=/; SameSite=Lax; HttpOnly")
        return resp


class CompressionMiddleware:
    """Transparent gzip/deflate compression for normal in-memory responses.

    StreamResponse is deliberately skipped because chunked streaming compression
    would require a different framing contract.
    """
    COMPRESSIBLE_PREFIXES = ("text/", "application/json", "application/javascript", "application/xml", "image/svg+xml")

    def __init__(self, min_size: int = 500, compresslevel: int = 6) -> None:
        self.min_size = min_size
        self.compresslevel = compresslevel

    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        resp = call_next(req)
        if isinstance(resp, StreamResponse):
            return resp
        if resp.headers.get("Content-Encoding") or len(resp.body) < self.min_size:
            return resp
        ctype = resp.content_type.lower()
        if not any(ctype.startswith(prefix) for prefix in self.COMPRESSIBLE_PREFIXES):
            return resp
        accept = req.header("accept-encoding").lower()
        if "gzip" in accept:
            resp.body = gzip.compress(resp.body, compresslevel=self.compresslevel)
            resp.headers["Content-Encoding"] = "gzip"
        elif "deflate" in accept:
            resp.body = zlib.compress(resp.body, level=self.compresslevel)
            resp.headers["Content-Encoding"] = "deflate"
        else:
            return resp
        resp.headers["Vary"] = "Accept-Encoding"
        resp.headers["Content-Length"] = str(len(resp.body))
        return resp

class GZipMiddleware(CompressionMiddleware):
    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        resp = call_next(req)
        if isinstance(resp, StreamResponse):
            return resp
        if resp.headers.get("Content-Encoding") or len(resp.body) < self.min_size:
            return resp
        ctype = resp.content_type.lower()
        if not any(ctype.startswith(prefix) for prefix in self.COMPRESSIBLE_PREFIXES):
            return resp
        if "gzip" not in req.header("accept-encoding").lower():
            return resp
        resp.body = gzip.compress(resp.body, compresslevel=self.compresslevel)
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
        resp.headers["Content-Length"] = str(len(resp.body))
        return resp
