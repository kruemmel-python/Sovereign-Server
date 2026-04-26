from __future__ import annotations
import email.utils, html, posixpath, re
from pathlib import Path
from urllib.parse import unquote
from .errors import HTTPError

_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_ROUTE_PARAM = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>")

def now_http_date() -> str:
    return email.utils.formatdate(usegmt=True)

def escape(value: object) -> str:
    return html.escape(str(value), quote=True)

def safe_join(base: Path, user_path: str) -> Path:
    base = base.resolve()
    user_path = unquote(user_path.replace("\\", "/"))
    user_path = posixpath.normpath("/" + user_path).lstrip("/")
    target = (base / user_path).resolve()
    if base != target and base not in target.parents:
        raise HTTPError(403, "Path traversal blocked")
    return target

def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or "upload.bin"
    return name[:max_len]
