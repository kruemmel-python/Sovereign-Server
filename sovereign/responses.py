from __future__ import annotations
import json
from typing import Any, Iterable, Iterator, Mapping, Optional, Union

class Response:
    def __init__(self, body: Union[str, bytes] = b"", status: int = 200,
                 headers: Optional[Mapping[str, str]] = None,
                 content_type: str = "text/html; charset=utf-8") -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = dict(headers or {})
        self.content_type = content_type

class JSONResponse(Response):
    def __init__(self, data: Any, status: int = 200, headers: Optional[Mapping[str, str]] = None) -> None:
        super().__init__(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                         status=status, headers=headers, content_type="application/json; charset=utf-8")

class StreamResponse:
    def __init__(self, chunks: Iterable[bytes], status: int = 200,
                 headers: Optional[Mapping[str, str]] = None,
                 content_type: str = "application/octet-stream") -> None:
        self.chunks = chunks
        self.status = status
        self.headers = dict(headers or {})
        self.content_type = content_type

class SSEResponse(StreamResponse):
    def __init__(self, events: Iterable[tuple[str, Any]], status: int = 200,
                 headers: Optional[Mapping[str, str]] = None) -> None:
        def gen() -> Iterator[bytes]:
            for event, data in events:
                payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                yield f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
        base = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        base.update(headers or {})
        super().__init__(gen(), status=status, headers=base, content_type="text/event-stream; charset=utf-8")
