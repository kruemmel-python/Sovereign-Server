from __future__ import annotations
import importlib, json, logging, sqlite3, threading, time, traceback
from pathlib import Path
from typing import Callable

logger = logging.getLogger("sovereign.tasks")

class SQLiteTaskQueue:
    def __init__(self, path: Path, poll_interval: float = 0.5, max_retries: int = 3) -> None:
        self.path = Path(path)
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise sqlite3.OperationalError(
                f"unable to create task database directory {self.path.parent!s}: {exc}"
            ) from exc
        if not self.path.parent.exists():
            raise sqlite3.OperationalError(f"task database directory does not exist: {self.path.parent!s}")
        with self._connect() as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                func TEXT NOT NULL,
                args TEXT NOT NULL,
                kwargs TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_run REAL NOT NULL,
                last_error TEXT
            )""")

    def enqueue(self, func: Callable[..., object], *args: object, **kwargs: object) -> int:
        name = f"{func.__module__}:{func.__qualname__}"
        with self._connect() as con:
            cur = con.execute("INSERT INTO tasks(func,args,kwargs,next_run) VALUES(?,?,?,?)",
                              (name, json.dumps(args), json.dumps(kwargs), time.time()))
            return int(cur.lastrowid)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run_forever, name="sovereign-task-worker", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout)

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            self.run_once()
            time.sleep(self.poll_interval)

    def run_once(self) -> None:
        with self._connect() as con:
            row = con.execute("SELECT id,func,args,kwargs,attempts FROM tasks WHERE status='pending' AND next_run<=? ORDER BY id LIMIT 1",
                              (time.time(),)).fetchone()
            if not row:
                return
            task_id, func_name, args_json, kwargs_json, attempts = row
            con.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
        try:
            module_name, qualname = func_name.split(":", 1)
            obj = importlib.import_module(module_name)
            for part in qualname.split("."):
                obj = getattr(obj, part)
            obj(*json.loads(args_json), **json.loads(kwargs_json))
            with self._connect() as con:
                con.execute("UPDATE tasks SET status='done' WHERE id=?", (task_id,))
        except Exception as exc:
            attempts += 1
            logger.error("persistent task failed: %s\n%s", func_name, traceback.format_exc())
            status = "dead" if attempts >= self.max_retries else "pending"
            delay = min(60, 2 ** attempts)
            with self._connect() as con:
                con.execute("UPDATE tasks SET status=?, attempts=?, next_run=?, last_error=? WHERE id=?",
                            (status, attempts, time.time() + delay, str(exc), task_id))
