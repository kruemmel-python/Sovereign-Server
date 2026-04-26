from __future__ import annotations

import sqlite3, threading, time
from pathlib import Path

class SQLiteJWTBlocklist:
    def __init__(self, path: str | Path = "sovereign_tasks.sqlite3", cache_ttl: float = 5.0) -> None:
        self.path = Path(path)
        self.cache_ttl = cache_ttl
        self.lock = threading.RLock()
        self._cache: dict[str, tuple[bool, float]] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS jwt_blocklist (
                jti TEXT PRIMARY KEY,
                exp INTEGER NOT NULL,
                revoked_at INTEGER NOT NULL,
                reason TEXT
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_jwt_blocklist_exp ON jwt_blocklist(exp)")

    def revoke(self, jti: str, exp: int, reason: str = "") -> None:
        if not jti:
            raise ValueError("jti is required")
        now = int(time.time())
        with self.lock, self._connect() as con:
            con.execute("""
            INSERT INTO jwt_blocklist(jti,exp,revoked_at,reason) VALUES(?,?,?,?)
            ON CONFLICT(jti) DO UPDATE SET exp=excluded.exp, revoked_at=excluded.revoked_at, reason=excluded.reason
            """, (jti, int(exp), now, reason))
            self._cache[jti] = (True, time.monotonic() + self.cache_ttl)

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        now_mono = time.monotonic()
        cached = self._cache.get(jti)
        if cached and cached[1] > now_mono:
            return cached[0]
        now = int(time.time())
        with self.lock, self._connect() as con:
            row = con.execute("SELECT 1 FROM jwt_blocklist WHERE jti=? AND exp>=?", (jti, now)).fetchone()
            revoked = row is not None
            self._cache[jti] = (revoked, now_mono + self.cache_ttl)
            return revoked

    def cleanup_expired(self) -> int:
        now = int(time.time())
        with self.lock, self._connect() as con:
            cur = con.execute("DELETE FROM jwt_blocklist WHERE exp < ?", (now,))
            self._cache.clear()
            return int(cur.rowcount or 0)

    def enqueue_cleanup(self, task_queue: object) -> object:
        """Queue cleanup via Sovereign's SQLiteTaskQueue-compatible interface."""
        return getattr(task_queue, "enqueue")(cleanup_jwt_blocklist, str(self.path))


def cleanup_jwt_blocklist(db_path: str) -> int:
    """Persistent-task compatible cleanup entrypoint."""
    return SQLiteJWTBlocklist(db_path).cleanup_expired()
