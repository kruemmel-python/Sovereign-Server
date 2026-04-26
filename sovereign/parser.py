from __future__ import annotations
import socket, tempfile, time
from typing import Dict, Tuple, Union
from .config import ServerConfig
from .errors import ClientClosed, HTTPError
from .request import Request
from .utils import _TOKEN

class SocketReader:
    def __init__(self, sock: socket.socket, config: ServerConfig) -> None:
        self.sock = sock
        self.config = config
        self.buffer = bytearray()
        self.absolute_deadline = time.monotonic() + config.absolute_request_timeout

    def _recv_some(self, timeout: float) -> bytes:
        remaining_absolute = self.absolute_deadline - time.monotonic()
        if remaining_absolute <= 0:
            raise HTTPError(408, "Absolute request timeout exceeded")
        self.sock.settimeout(max(0.001, min(timeout, remaining_absolute)))
        try:
            data = self.sock.recv(4096)
        except socket.timeout as exc:
            raise HTTPError(408, "Request Timeout") from exc
        if not data:
            raise ClientClosed()
        return data

    def _read_until(self, marker: bytes, limit: int, idle_timeout: float) -> bytes:
        while marker not in self.buffer:
            if len(self.buffer) > limit:
                raise HTTPError(431, "Read limit exceeded")
            self.buffer.extend(self._recv_some(idle_timeout))
        idx = self.buffer.index(marker) + len(marker)
        data = bytes(self.buffer[:idx])
        del self.buffer[:idx]
        return data

    def read_headers(self) -> bytes:
        return self._read_until(b"\r\n\r\n", self.config.max_header_bytes + 4, self.config.header_idle_timeout)

    def read_exact(self, n: int) -> bytes:
        out = bytearray()
        take = min(n, len(self.buffer))
        out.extend(self.buffer[:take])
        del self.buffer[:take]
        while len(out) < n:
            chunk = self._recv_some(self.config.body_idle_timeout)
            need = n - len(out)
            out.extend(chunk[:need])
            if len(chunk) > need:
                self.buffer.extend(chunk[need:])
        return bytes(out)

    def read_exact_body(self, length: int) -> Union[bytes, tempfile.SpooledTemporaryFile]:
        if length > self.config.max_body_bytes:
            raise HTTPError(413, "Payload Too Large")
        if length <= self.config.max_memory_body:
            return self.read_exact(length)
        spool = tempfile.SpooledTemporaryFile(max_size=self.config.max_memory_body, mode="w+b")
        remaining = length
        while remaining:
            part = self.read_exact(min(65536, remaining))
            spool.write(part)
            remaining -= len(part)
        spool.seek(0)
        return spool

    def read_chunked_body(self) -> tuple[Union[bytes, tempfile.SpooledTemporaryFile], int]:
        spool = tempfile.SpooledTemporaryFile(max_size=self.config.max_memory_body, mode="w+b")
        total = 0
        while True:
            line = self._read_until(b"\r\n", 8192, self.config.body_idle_timeout)[:-2]
            if b";" in line:
                line = line.split(b";", 1)[0]
            try:
                size = int(line.strip(), 16)
            except ValueError as exc:
                raise HTTPError(400, "Invalid chunk size") from exc
            if size == 0:
                # Consume trailer section; bounded.
                self._read_until(b"\r\n", 8192, self.config.body_idle_timeout)
                break
            total += size
            if total > self.config.max_body_bytes:
                raise HTTPError(413, "Payload Too Large")
            spool.write(self.read_exact(size))
            crlf = self.read_exact(2)
            if crlf != b"\r\n":
                raise HTTPError(400, "Malformed chunk terminator")
        spool.seek(0)
        if total <= self.config.max_memory_body:
            return spool.read(), total
        return spool, total

def parse_header_block(raw: bytes, config: ServerConfig) -> Tuple[str, str, str, Dict[str, str], Tuple[Tuple[str, str], ...]]:
    text = raw.decode("iso-8859-1", errors="strict")
    if "\r\n\r\n" not in text:
        raise HTTPError(400, "Malformed headers")
    lines = text[:-4].split("\r\n")
    if not lines or not lines[0]:
        raise HTTPError(400, "Missing request line")
    if len(lines[0]) > config.max_request_line:
        raise HTTPError(414, "Request line too long")
    parts = lines[0].split(" ")
    if len(parts) != 3:
        raise HTTPError(400, "Invalid request line")
    method, target, version = parts
    if not _TOKEN.match(method):
        raise HTTPError(400, "Invalid method")
    if version != "HTTP/1.1":
        raise HTTPError(505, "Only HTTP/1.1 supported")
    if not target.startswith("/"):
        raise HTTPError(400, "Only origin-form request target supported")
    headers: Dict[str, str] = {}
    raw_pairs = []
    if len(lines) - 1 > config.max_headers:
        raise HTTPError(431, "Too many headers")
    for line in lines[1:]:
        if not line:
            continue
        if line[0] in " \t":
            raise HTTPError(400, "Folded headers rejected")
        if ":" not in line:
            raise HTTPError(400, "Malformed header")
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if not name or not _TOKEN.match(name):
            raise HTTPError(400, "Invalid header name")
        if len(name) > config.max_header_name or len(value) > config.max_header_value:
            raise HTTPError(431, "Header field too large")
        if name in headers and name in {"host", "content-length", "transfer-encoding"}:
            raise HTTPError(400, f"Duplicate {name} rejected")
        headers[name] = value if name not in headers else headers[name] + ", " + value
        raw_pairs.append((name, value))
    if "host" not in headers:
        raise HTTPError(400, "Host header required")
    if "content-length" in headers and "transfer-encoding" in headers:
        raise HTTPError(400, "Content-Length with Transfer-Encoding rejected")
    return method.upper(), target, version, headers, tuple(raw_pairs)

def parse_request(reader: SocketReader, addr: tuple[str, int], config: ServerConfig, app_state: dict | None = None) -> Request:
    method, target, version, headers, raw_pairs = parse_header_block(reader.read_headers(), config)
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body, size = reader.read_chunked_body()
    else:
        cl = headers.get("content-length", "0")
        if not cl.isdigit():
            raise HTTPError(400, "Invalid Content-Length")
        size = int(cl)
        body = reader.read_exact_body(size) if size else b""
    return Request(method, target, version, headers, raw_pairs, body, size, addr, config, app_state=app_state or {})
