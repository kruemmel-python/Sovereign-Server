from __future__ import annotations
import hashlib, mimetypes
from .errors import HTTPError
from .request import Request
from .responses import Response
from .utils import safe_join

def _etag(path) -> str:
    st = path.stat()
    return '"' + hashlib.sha256(f"{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:32] + '"'

def static_response(req: Request, prefix: str = "/static/") -> Response:
    path = safe_join(req.config.static_dir, req.path[len(prefix):])
    if not path.exists() or not path.is_file():
        raise HTTPError(404, "Static file not found")
    etag = _etag(path)
    headers = {
        "Cache-Control": "public, max-age=3600",
        "ETag": etag,
        "Last-Modified": __import__("email.utils").utils.formatdate(path.stat().st_mtime, usegmt=True),
    }
    if req.header("if-none-match") == etag:
        return Response(b"", status=304, headers=headers)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(path.read_bytes(), content_type=mime, headers=headers)
