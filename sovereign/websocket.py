from __future__ import annotations

import base64, hashlib, os, queue, socket, threading, time
from typing import Any

from .errors import HTTPError, WebSocketClosed
from .request import Request

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

class WebSocketSession:
    def __init__(self, sock: socket.socket, req: Request, *, user_id: str | None = None,
                 heartbeat_interval: float = 25.0, heartbeat_timeout: float = 10.0) -> None:
        self.sock = sock
        self.req = req
        self.user_id = user_id or self._infer_user_id(req)
        self.id = req.request_id
        self.closed = False
        self.max_payload = req.config.websocket_max_payload
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.last_pong = time.monotonic()
        self._pending_ping: bytes | None = None
        self._close_lock = threading.RLock()
        self.presence: dict[str, Any] = {}
        self.send_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=req.config.websocket_queue_size)
        self.writer = threading.Thread(target=self._writer_loop, daemon=True, name=f"ws-writer-{req.request_id}")
        self.writer.start()
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True, name=f"ws-heartbeat-{req.request_id}")
        self.heartbeat_thread.start()

    def _infer_user_id(self, req: Request) -> str | None:
        if isinstance(req.user, dict):
            value = req.user.get("sub") or req.user.get("id")
            return str(value) if value is not None else None
        return None

    def _writer_loop(self) -> None:
        while True:
            item = self.send_queue.get()
            if item is None:
                return
            try:
                self.sock.settimeout(self.req.config.websocket_send_timeout)
                self.sock.sendall(item)
            except Exception:
                self.closed = True
                return

    def _enqueue_frame(self, frame: bytes) -> None:
        if self.closed:
            raise WebSocketClosed()
        try:
            self.send_queue.put_nowait(frame)
        except queue.Full:
            self.close(1008, "send queue full")
            raise WebSocketClosed()

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            try:
                self.sock.settimeout(self.heartbeat_interval + self.heartbeat_timeout)
                chunk = self.sock.recv(n - len(buf))
            except socket.timeout as exc:
                raise WebSocketClosed() from exc
            if not chunk:
                raise WebSocketClosed()
            buf.extend(chunk)
        return bytes(buf)

    def recv(self) -> tuple[int, bytes]:
        h = self._read_exact(2)
        b1, b2 = h
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if not masked:
            self.close(1002, "client frames must be masked")
            raise WebSocketClosed()
        if length == 126:
            length = int.from_bytes(self._read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._read_exact(8), "big")
        if length > self.max_payload:
            self.close(1009, "message too large")
            raise WebSocketClosed()
        mask = self._read_exact(4)
        payload = bytearray(self._read_exact(length))
        for i in range(length):
            payload[i] ^= mask[i % 4]
        data = bytes(payload)
        if opcode == 8:
            self.close()
            raise WebSocketClosed()
        if opcode == 9:
            self._send_frame(10, data)
            return self.recv()
        if opcode == 10:
            if self._pending_ping is None or data == self._pending_ping:
                self.last_pong = time.monotonic()
                self._pending_ping = None
            return self.recv()
        return opcode, data

    def receive_text(self) -> str:
        opcode, payload = self.recv()
        if opcode != 1:
            raise WebSocketClosed()
        return payload.decode("utf-8")

    def send_text(self, text: str) -> None:
        self._send_frame(1, text.encode("utf-8"))

    def send_json(self, event: str, data: Any) -> None:
        import json
        self.send_text(json.dumps({"event": event, "data": data}, ensure_ascii=False, separators=(",", ":")))

    def send_binary(self, data: bytes) -> None:
        self._send_frame(2, data)

    def ping(self, payload: bytes | None = None) -> None:
        payload = payload if payload is not None else os.urandom(8)
        self._pending_ping = payload
        self._send_frame(9, payload)

    def heartbeat(self) -> None:
        while not self.closed:
            time.sleep(self.heartbeat_interval)
            if self.closed:
                return
            if self._pending_ping is not None and (time.monotonic() - self.last_pong) > self.heartbeat_timeout:
                self.close(1002, "heartbeat timeout")
                return
            try:
                self.ping()
            except Exception:
                self.close()
                return

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        first = 0x80 | opcode
        n = len(payload)
        if n < 126:
            header = bytes([first, n])
        elif n <= 0xFFFF:
            header = bytes([first, 126]) + n.to_bytes(2, "big")
        else:
            header = bytes([first, 127]) + n.to_bytes(8, "big")
        self._enqueue_frame(header + payload)

    def close(self, code: int = 1000, reason: str = "") -> None:
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                payload = code.to_bytes(2, "big") + reason.encode("utf-8")[:120]
                frame = bytes([0x88, len(payload)]) + payload
                self.send_queue.put_nowait(frame)
            except Exception:
                pass
            try:
                self.send_queue.put_nowait(None)
            except Exception:
                pass
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

def is_websocket_upgrade(req: Request) -> bool:
    return req.header("upgrade").lower() == "websocket" and "upgrade" in req.header("connection").lower()

def handshake(sock: socket.socket, req: Request) -> None:
    key = req.header("sec-websocket-key")
    if req.method != "GET" or req.header("sec-websocket-version") != "13" or not key:
        raise HTTPError(400, "Invalid WebSocket handshake")
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError()
    except Exception as exc:
        raise HTTPError(400, "Invalid WebSocket key") from exc
    accept = base64.b64encode(hashlib.sha1((key + _GUID).encode("ascii")).digest()).decode("ascii")
    raw = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode("ascii")
    sock.sendall(raw)
