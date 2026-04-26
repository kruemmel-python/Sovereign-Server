from __future__ import annotations
import dataclasses, io, json, tempfile
from typing import Any, Callable, Dict, Mapping, Tuple, Union
from urllib.parse import parse_qs, urlsplit

BackgroundTask = tuple[Callable[..., object], tuple, dict]

@dataclasses.dataclass
class Request:
    method: str
    target: str
    version: str
    headers: Mapping[str, str]
    raw_headers: Tuple[Tuple[str, str], ...]
    body: Union[bytes, tempfile.SpooledTemporaryFile]
    body_size: int
    client_addr: Tuple[str, int]
    config: object
    app_state: dict = dataclasses.field(default_factory=dict)
    route_params: Dict[str, str] = dataclasses.field(default_factory=dict)
    request_id: str = "-"
    user: Any = None
    validated_data: Any = None
    background_tasks: list[BackgroundTask] = dataclasses.field(default_factory=list)
    di_cache: dict[object, object] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        split = urlsplit(self.target)
        self.path = split.path or "/"
        self.query_string = split.query
        self.query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(split.query, keep_blank_values=True).items()}
        self.remote_addr = self.client_addr[0]
        self.cookies = self._parse_cookies()

    def _parse_cookies(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in self.header("cookie").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    def body_bytes(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        self.body.seek(0)
        return self.body.read()

    def body_stream(self) -> io.BufferedIOBase:
        if isinstance(self.body, bytes):
            return io.BytesIO(self.body)
        self.body.seek(0)
        return self.body

    def json(self) -> Any:
        return json.loads(self.body_bytes().decode("utf-8"))

    def multipart(self, **limits: int):
        from .multipart import parse_multipart
        return parse_multipart(self, **limits)

    def add_background_task(self, func: Callable[..., object], *args: object, persistent: bool = False, **kwargs: object) -> None:
        self.background_tasks.append((func, args, {**kwargs, "_persistent": persistent}))
