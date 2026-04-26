from __future__ import annotations

import json, queue, threading, time
from collections import defaultdict
from typing import Any, Iterable, Protocol, Set

from .responses import SSEResponse
from .websocket import WebSocketSession


class ClientConnection(Protocol):
    id: str
    user_id: str | None
    presence: dict[str, Any]
    closed: bool
    def send_event(self, event: str, data: Any) -> None: ...
    def close(self) -> None: ...


class SSESession:
    """Queue-backed Server-Sent Events connection compatible with EventHub."""

    def __init__(self, *, user_id: str | None = None, max_queue: int = 256,
                 heartbeat_interval: float = 15.0) -> None:
        self.id = f"sse-{id(self):x}"
        self.user_id = user_id
        self.presence: dict[str, Any] = {"online_at": time.time(), "transport": "sse"}
        self.closed = False
        self.heartbeat_interval = heartbeat_interval
        self.queue: queue.Queue[tuple[str, Any] | None] = queue.Queue(maxsize=max_queue)

    def send_event(self, event: str, data: Any) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait((event, data))
        except queue.Full:
            self.close()

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.queue.put_nowait(None)
            except Exception:
                pass

    def events(self) -> Iterable[tuple[str, Any]]:
        last_heartbeat = time.monotonic()
        while not self.closed:
            timeout = max(0.1, self.heartbeat_interval - (time.monotonic() - last_heartbeat))
            try:
                item = self.queue.get(timeout=timeout)
            except queue.Empty:
                last_heartbeat = time.monotonic()
                yield ("heartbeat", {"ts": time.time()})
                continue
            if item is None:
                break
            yield item


class WebSocketConnection:
    def __init__(self, ws: WebSocketSession) -> None:
        self.ws = ws
        self.id = ws.id
        self.user_id = ws.user_id
        self.presence = ws.presence
        self.closed = ws.closed

    def send_event(self, event: str, data: Any) -> None:
        if hasattr(self.ws, "send_json"):
            self.ws.send_json(event, data)
        else:
            self.ws.send_text(json.dumps({"event": event, "data": data}, ensure_ascii=False, separators=(",", ":")))

    def close(self) -> None:
        self.ws.close()


class EventHub:
    """Universal room/user hub for WebSockets and SSE clients."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.rooms: dict[str, Set[Any]] = defaultdict(set)
        self.users: dict[str, Set[Any]] = defaultdict(set)
        self.sessions: set[Any] = set()

    def register(self, conn: Any, user_id: str | None = None, **presence: Any) -> Any:
        if isinstance(conn, WebSocketSession):
            conn = WebSocketConnection(conn)
        with self.lock:
            if user_id is not None:
                conn.user_id = str(user_id)
            conn.presence.update(presence)
            conn.presence.setdefault("online_at", time.time())
            self.sessions.add(conn)
            if conn.user_id:
                self.users[str(conn.user_id)].add(conn)
        return conn

    def unregister(self, conn: Any) -> None:
        with self.lock:
            self.sessions.discard(conn)
            for room in list(self.rooms):
                self.rooms[room].discard(conn)
                if not self.rooms[room]:
                    self.rooms.pop(room, None)
            uid = getattr(conn, "user_id", None)
            if uid:
                self.users.get(str(uid), set()).discard(conn)
                if not self.users.get(str(uid)):
                    self.users.pop(str(uid), None)
        try:
            conn.close()
        except Exception:
            pass

    def join(self, room: str, conn: Any) -> Any:
        conn = self.register(conn)
        with self.lock:
            self.rooms[room].add(conn)
        return conn

    def leave(self, room: str, conn: Any) -> None:
        with self.lock:
            self.rooms.get(room, set()).discard(conn)
            if not self.rooms.get(room):
                self.rooms.pop(room, None)

    def sse(self, room: str, *, user_id: str | None = None, **presence: Any) -> SSEResponse:
        session = SSESession(user_id=user_id)
        self.join(room, session)
        self.register(session, user_id=user_id, **presence)
        def generator():
            try:
                yield from session.events()
            finally:
                self.unregister(session)
        return SSEResponse(generator())

    def online_users(self) -> list[str]:
        with self.lock:
            return sorted(self.users)

    def is_online(self, user_id: str) -> bool:
        with self.lock:
            return bool(self.users.get(str(user_id)))

    def user_sessions(self, user_id: str) -> list[Any]:
        with self.lock:
            return list(self.users.get(str(user_id), ()))

    def broadcast(self, room: str, message: Any, event: str = "message") -> None:
        self.broadcast_event(room, event, message)

    def broadcast_event(self, room: str, event: str, data: Any) -> None:
        with self.lock:
            targets = list(self.rooms.get(room, ()))
        self._send_many(targets, event, data)

    def send_user(self, user_id: str, message: Any, event: str = "message") -> None:
        with self.lock:
            targets = list(self.users.get(str(user_id), ()))
        self._send_many(targets, event, message)

    def _send_many(self, targets: list[Any], event: str, data: Any) -> None:
        dead = []
        for conn in targets:
            try:
                if getattr(conn, "closed", False):
                    dead.append(conn)
                    continue
                conn.send_event(event, data)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.unregister(conn)


event_hub = EventHub()
