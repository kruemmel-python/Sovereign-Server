from __future__ import annotations

import dataclasses
import gzip
import hashlib
import html
import mimetypes
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .errors import HTTPError
from .request import Request
from .responses import Response
from .utils import safe_join


_HTML5_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".wasm": "application/wasm",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def guess_html5_type(path: Path) -> str:
    return _HTML5_MIME_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class HTMLResponse(Response):
    """Explicit HTML5 response with UTF-8 content type."""

    def __init__(self, body: str | bytes, status: int = 200, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(body, status=status, headers=headers, content_type="text/html; charset=utf-8")


@dataclasses.dataclass(frozen=True)
class AssetInfo:
    path: str
    size: int
    sha256: str
    integrity: str
    content_type: str


class AssetManifest:
    """Tiny dependency-free asset manifest for cache busting and SRI metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def scan(self) -> dict[str, AssetInfo]:
        manifest: dict[str, AssetInfo] = {}
        if not self.root.exists():
            return manifest
        for path in sorted(p for p in self.root.rglob("*") if p.is_file()):
            rel = "/" + path.relative_to(self.root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[rel] = AssetInfo(
                path=rel,
                size=path.stat().st_size,
                sha256=digest,
                integrity="sha256-" + __import__("base64").b64encode(bytes.fromhex(digest)).decode("ascii"),
                content_type=guess_html5_type(path),
            )
        return manifest

    def as_jsonable(self) -> dict[str, dict[str, Any]]:
        return {k: dataclasses.asdict(v) for k, v in self.scan().items()}


class CSP:
    """Small Content-Security-Policy builder.

    Defaults are intentionally strict.  Apps that need external CDNs, inline
    scripts or web workers can opt in explicitly instead of weakening the
    global server defaults.
    """

    def __init__(self, **directives: str | Iterable[str]) -> None:
        self.directives: dict[str, tuple[str, ...]] = {
            "default-src": ("'self'",),
            "base-uri": ("'none'",),
            "object-src": ("'none'",),
            "frame-ancestors": ("'none'",),
            "img-src": ("'self'", "data:"),
            "font-src": ("'self'", "data:"),
            "style-src": ("'self'",),
            "script-src": ("'self'",),
            "connect-src": ("'self'",),
            "form-action": ("'self'",),
            "manifest-src": ("'self'",),
            "worker-src": ("'self'",),
        }
        for key, value in directives.items():
            self.set(key.replace("_", "-"), value)

    def set(self, name: str, value: str | Iterable[str]) -> "CSP":
        if isinstance(value, str):
            parts = tuple(v for v in value.split(" ") if v)
        else:
            parts = tuple(value)
        self.directives[name] = parts
        return self

    def __str__(self) -> str:
        return "; ".join(f"{k} {' '.join(v)}" for k, v in self.directives.items())


class HTML5SecurityHeadersMiddleware:
    """Browser hardening middleware for HTML5 apps."""

    def __init__(
        self,
        *,
        csp: CSP | str | None = None,
        hsts: bool = False,
        cross_origin_isolation: bool = False,
        permissions_policy: str = "geolocation=(), microphone=(), camera=(), payment=()",
    ) -> None:
        self.csp = str(csp or CSP())
        self.hsts = hsts
        self.cross_origin_isolation = cross_origin_isolation
        self.permissions_policy = permissions_policy

    def _apply(self, resp: Response) -> Response:
        if hasattr(resp, "headers"):
            headers = resp.headers
            headers.setdefault("X-Content-Type-Options", "nosniff")
            headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            headers.setdefault("Permissions-Policy", self.permissions_policy)
            headers.setdefault("Content-Security-Policy", self.csp)
            if self.hsts:
                headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            if self.cross_origin_isolation:
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return resp

    def __call__(self, req: Request, call_next: Callable[[Request], Response]) -> Response:
        resp = call_next(req)
        if hasattr(resp, "__await__"):
            async def finalize():
                return self._apply(await resp)
            return finalize()
        return self._apply(resp)


def _etag(path: Path) -> str:
    st = path.stat()
    return '"' + hashlib.sha256(f"{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:32] + '"'


def _range_response(req: Request, path: Path, body: bytes, headers: dict[str, str], content_type: str) -> Response | None:
    header = req.header("range")
    if not header or not header.startswith("bytes="):
        return None
    try:
        raw_start, raw_end = header[6:].split("-", 1)
        size = len(body)
        if raw_start == "":
            length = int(raw_end)
            start = max(size - length, 0)
            end = size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
        if start < 0 or end < start or start >= size:
            raise ValueError
        end = min(end, size - 1)
    except Exception:
        raise HTTPError(416, "Requested Range Not Satisfiable", headers={"Content-Range": f"bytes */{len(body)}"})
    chunk = body[start : end + 1]
    headers = {**headers, "Content-Range": f"bytes {start}-{end}/{len(body)}", "Content-Length": str(len(chunk))}
    return Response(chunk, status=206, headers=headers, content_type=content_type)


def serve_html5_file(
    req: Request,
    root: str | Path,
    asset_path: str,
    *,
    index: str = "index.html",
    spa_fallback: bool = False,
    immutable_assets: bool = True,
    max_age: int = 3600,
) -> Response:
    root_path = Path(root).resolve()
    wanted = asset_path.lstrip("/") or index
    candidate = safe_join(root_path, wanted)

    if candidate.is_dir():
        candidate = safe_join(candidate, index)

    if (not candidate.exists() or not candidate.is_file()) and spa_fallback:
        accept = req.header("accept")
        if req.method in {"GET", "HEAD"} and ("text/html" in accept or "*/*" in accept or not accept):
            candidate = safe_join(root_path, index)

    if not candidate.exists() or not candidate.is_file():
        raise HTTPError(404, "HTML5 asset not found")

    etag = _etag(candidate)
    rel = candidate.relative_to(root_path).as_posix()
    is_fingerprinted = bool(__import__("re").search(r"[.-][a-fA-F0-9]{8,}\.", candidate.name))
    cache = f"public, max-age={31536000 if is_fingerprinted and immutable_assets else max_age}"
    if is_fingerprinted and immutable_assets:
        cache += ", immutable"

    headers = {
        "Cache-Control": cache,
        "ETag": etag,
        "Last-Modified": __import__("email.utils").utils.formatdate(candidate.stat().st_mtime, usegmt=True),
        "Accept-Ranges": "bytes",
        "X-Sovereign-Asset": "/" + rel,
    }
    if req.header("if-none-match") == etag:
        return Response(b"", status=304, headers=headers, content_type=guess_html5_type(candidate))

    body = candidate.read_bytes()
    content_type = guess_html5_type(candidate)

    ranged = _range_response(req, candidate, body, headers, content_type)
    if ranged is not None:
        return ranged

    accept_encoding = req.header("accept-encoding")
    if "gzip" in accept_encoding and len(body) > 512 and content_type.startswith(("text/", "application/json", "application/javascript", "image/svg")):
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"

    return Response(body, headers=headers, content_type=content_type)


@dataclasses.dataclass
class HTML5App:
    """Mounts a small HTML5 site, SPA, PWA or static frontend on a Router."""

    root: str | Path = "web"
    prefix: str = "/"
    index: str = "index.html"
    assets_prefix: str = "/assets"
    spa_fallback: bool = True
    security_headers: bool = True
    expose_manifest: bool = True

    def mount(self, router: Any) -> "HTML5App":
        root = Path(self.root).resolve()
        prefix = "/" + self.prefix.strip("/") if self.prefix.strip("/") else ""
        assets_prefix = "/" + self.assets_prefix.strip("/")

        if self.security_headers:
            router.middleware(HTML5SecurityHeadersMiddleware())

        if self.expose_manifest:
            @router.route("/__assets.json")
            def assets_manifest(req: Request):
                from .responses import JSONResponse
                return JSONResponse(AssetManifest(root).as_jsonable())

        @router.route(assets_prefix + "/{asset_path:path}", methods=("GET", "HEAD"))
        def html5_asset(req: Request):
            asset_path = assets_prefix.strip("/") + "/" + req.route_params.get("asset_path", "")
            return serve_html5_file(req, root, asset_path, index=self.index, spa_fallback=False)

        @router.route((prefix or "/") + "{page_path:path}", methods=("GET", "HEAD"))
        def html5_page(req: Request):
            page = req.route_params.get("page_path", "")
            return serve_html5_file(req, root, page, index=self.index, spa_fallback=self.spa_fallback)

        return self


def escape_html(value: Any) -> str:
    return html.escape(str(value), quote=True)
