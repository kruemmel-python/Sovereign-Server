from __future__ import annotations

import sqlite3, threading, time
from pathlib import Path
from typing import Callable, Literal

from .errors import HTTPError
from .request import Request
from .responses import Response, StreamResponse

HandlerResult = Response | StreamResponse
Storage = Literal["memory", "sqlite"]

class TokenBucketLimiter:
    def __init__(self, requests: int, window: int, *, storage: Storage = "memory",
                 db_path: str | Path = "sovereign_tasks.sqlite3",
                 key_func: Callable[[Request], str] | None = None) -> None:
        if requests <= 0 or window <= 0:
            raise ValueError("requests and window must be positive")
        self.capacity = float(requests)
        self.refill_rate = float(requests) / float(window)
        self.window = int(window)
        self.storage = storage
        self.db_path = Path(db_path)
        self.key_func = key_func or self.default_key
        self.lock = threading.RLock()
        self.buckets: dict[str, tuple[float, float]] = {}
        if storage == "sqlite":
            self._init_db()

    def default_key(self, req: Request) -> str:
        user = req.user
        if isinstance(user, dict) and user.get("sub"):
            return f"user:{user['sub']}"
        return f"ip:{req.remote_addr}"

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                key TEXT PRIMARY KEY,
                tokens REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")

    def _consume_memory(self, key: str, now: float) -> tuple[bool, float, float]:
        with self.lock:
            tokens, updated = self.buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - updated) * self.refill_rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            self.buckets[key] = (tokens, now)
            retry = 0.0 if allowed else (1.0 - tokens) / self.refill_rate
            return allowed, tokens, retry

    def _consume_sqlite(self, key: str, now: float) -> tuple[bool, float, float]:
        with self.lock, self._connect() as con:
            row = con.execute("SELECT tokens, updated_at FROM rate_limits WHERE key=?", (key,)).fetchone()
            tokens, updated = row if row else (self.capacity, now)
            tokens = min(self.capacity, float(tokens) + (now - float(updated)) * self.refill_rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            con.execute("""
            INSERT INTO rate_limits(key,tokens,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET tokens=excluded.tokens, updated_at=excluded.updated_at
            """, (key, tokens, now))
            con.execute("DELETE FROM rate_limits WHERE updated_at < ?", (now - max(self.window * 4, 3600),))
            retry = 0.0 if allowed else (1.0 - tokens) / self.refill_rate
            return allowed, tokens, retry

    def consume(self, key: str) -> tuple[bool, float, float]:
        if self.storage == "sqlite":
            return self._consume_sqlite(key, time.time())
        return self._consume_memory(key, time.monotonic())

    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        key = self.key_func(req)
        allowed, tokens, retry = self.consume(key)
        if not allowed:
            err = HTTPError(429, "Too Many Requests")
            setattr(err, "headers", {"Retry-After": str(max(1, int(retry + 0.999)))})
            raise err
        resp = call_next(req)
        resp.headers["X-RateLimit-Limit"] = str(int(self.capacity))
        resp.headers["X-RateLimit-Remaining"] = str(max(0, int(tokens)))
        return resp

def rate_limit(requests: int, window: int, *, storage: Storage = "memory",
               db_path: str | Path = "sovereign_tasks.sqlite3",
               key_func: Callable[[Request], str] | None = None) -> TokenBucketLimiter:
    return TokenBucketLimiter(requests, window, storage=storage, db_path=db_path, key_func=key_func)


class BruteForceProtector:
    """SQLite-backed adaptive tarpit/fail2ban guard for login-like routes."""

    def __init__(self, *, max_attempts: int = 5, block_seconds: int = 15 * 60,
                 db_path: str | Path = "sovereign_tasks.sqlite3",
                 key_func: Callable[[Request], str] | None = None,
                 base_delay: float = 2.0, max_delay: float = 16.0,
                 failure_statuses: tuple[int, ...] = (401, 403)) -> None:
        self.max_attempts = max_attempts
        self.block_seconds = block_seconds
        self.db_path = Path(db_path)
        self.key_func = key_func or self._default_key
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.failure_statuses = failure_statuses
        self.lock = threading.RLock()
        self._init_db()

    def _default_key(self, req: Request) -> str:
        try:
            data = req.json() if req.body_size else {}
            user = data.get("username") or data.get("email") or data.get("user_id")
        except Exception:
            user = None
        return f"login:{user or req.remote_addr}"

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS brute_force_attempts (
                key TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL,
                blocked_until REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )""")

    def status(self, key: str) -> tuple[int, float]:
        now = time.time()
        with self.lock, self._connect() as con:
            row = con.execute("SELECT attempts, blocked_until FROM brute_force_attempts WHERE key=?", (key,)).fetchone()
        if not row:
            return 0, 0.0
        attempts, blocked_until = int(row[0]), float(row[1])
        if blocked_until and blocked_until <= now:
            self.reset(key)
            return 0, 0.0
        return attempts, blocked_until

    def reset(self, key: str) -> None:
        with self.lock, self._connect() as con:
            con.execute("DELETE FROM brute_force_attempts WHERE key=?", (key,))

    def record_failure(self, key: str) -> tuple[int, float]:
        now = time.time()
        with self.lock, self._connect() as con:
            row = con.execute("SELECT attempts FROM brute_force_attempts WHERE key=?", (key,)).fetchone()
            attempts = (int(row[0]) if row else 0) + 1
            blocked_until = now + self.block_seconds if attempts >= self.max_attempts else 0.0
            con.execute("""
            INSERT INTO brute_force_attempts(key,attempts,blocked_until,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts, blocked_until=excluded.blocked_until, updated_at=excluded.updated_at
            """, (key, attempts, blocked_until, now))
            con.execute("DELETE FROM brute_force_attempts WHERE updated_at < ?", (now - max(self.block_seconds * 4, 86400),))
        return attempts, blocked_until

    def delay_for(self, attempts: int) -> float:
        if attempts < 3:
            return 0.0
        return min(self.max_delay, self.base_delay ** (attempts - 2))

    def __call__(self, req: Request, call_next: Callable[[Request], HandlerResult]) -> HandlerResult:
        key = self.key_func(req)
        attempts, blocked_until = self.status(key)
        now = time.time()
        if blocked_until > now:
            err = HTTPError(403, "Temporarily blocked")
            setattr(err, "headers", {"Retry-After": str(max(1, int(blocked_until - now)))})
            raise err
        delay = self.delay_for(attempts)
        if delay:
            time.sleep(delay)
        try:
            resp = call_next(req)
        except HTTPError as exc:
            if exc.status in self.failure_statuses:
                attempts, blocked_until = self.record_failure(key)
                delay = self.delay_for(attempts)
                if delay:
                    time.sleep(delay)
                if blocked_until > time.time():
                    setattr(exc, "headers", {"Retry-After": str(max(1, int(blocked_until - time.time())))})
            else:
                self.reset(key)
            raise
        if getattr(resp, "status", 200) in self.failure_statuses:
            attempts, blocked_until = self.record_failure(key)
            if blocked_until > time.time():
                resp.headers["Retry-After"] = str(max(1, int(blocked_until - time.time())))
        else:
            self.reset(key)
        return resp


def bruteforce_protect(*, max_attempts: int = 5, block_seconds: int = 15 * 60,
                       db_path: str | Path = "sovereign_tasks.sqlite3",
                       key_func: Callable[[Request], str] | None = None,
                       base_delay: float = 2.0, max_delay: float = 16.0) -> BruteForceProtector:
    return BruteForceProtector(max_attempts=max_attempts, block_seconds=block_seconds,
                               db_path=db_path, key_func=key_func,
                               base_delay=base_delay, max_delay=max_delay)
