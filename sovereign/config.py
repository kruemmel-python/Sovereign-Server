from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import Optional, Tuple

@dataclasses.dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    server_name: str = "Sovereign/7.0"

    static_dir: Path = Path("static")
    upload_dir: Path = Path("uploads")
    task_db: Path = Path("sovereign_tasks.sqlite3")

    max_request_line: int = 4096
    max_header_bytes: int = 16 * 1024
    max_headers: int = 96
    max_header_name: int = 96
    max_header_value: int = 8192
    max_body_bytes: int = 50 * 1024 * 1024
    max_memory_body: int = 512 * 1024

    header_idle_timeout: float = 3.0
    body_idle_timeout: float = 10.0
    absolute_request_timeout: float = 30.0
    keepalive_timeout: float = 5.0
    tls_handshake_timeout: float = 2.0
    max_keepalive_requests: int = 50

    listen_backlog: int = 256
    workers: int = 32
    max_concurrent_connections: int = 512
    graceful_shutdown_timeout: float = 20.0

    websocket_queue_size: int = 256
    websocket_send_timeout: float = 3.0
    websocket_max_payload: int = 2 * 1024 * 1024

    cors_allow_origins: Tuple[str, ...] = ("*",)
    cors_allow_methods: Tuple[str, ...] = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
    cors_allow_headers: Tuple[str, ...] = ("Content-Type", "Authorization", "X-Request-Id", "X-CSRF-Token")

    csrf_cookie_name: str = "sovereign_csrf"
    csrf_header_name: str = "x-csrf-token"

    tls_cert: Optional[Path] = None
    tls_key: Optional[Path] = None
    json_logs: bool = False

DEFAULT_CONFIG = ServerConfig()
