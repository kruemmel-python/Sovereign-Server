from __future__ import annotations
import concurrent.futures, dataclasses, logging, socket, ssl, threading, time, traceback
from .config import ServerConfig
from .errors import ClientClosed, HTTPError, STATUS_REASONS
from .logging_utils import configure_logging, new_request_id, set_request_id
from .parser import SocketReader, parse_request
from .request import Request
from .responses import Response, StreamResponse
from .router import Router
from .static import static_response
from .tasks import SQLiteTaskQueue
from .utils import now_http_date
from .websocket import WebSocketSession, handshake, is_websocket_upgrade

logger = logging.getLogger("sovereign.server")

def security_headers() -> dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    }

def send_headers(sock: socket.socket, config: ServerConfig, status: int, headers: dict[str, str], keep_alive: bool) -> None:
    merged = {"Date": now_http_date(), "Server": config.server_name, "Connection": "keep-alive" if keep_alive else "close"}
    if status != 101:
        merged.update(security_headers())
    merged.update(headers)
    reason = STATUS_REASONS.get(status, "OK")
    raw = [f"HTTP/1.1 {status} {reason}\r\n"]
    for k, v in merged.items():
        if "\r" in k or "\n" in k or "\r" in str(v) or "\n" in str(v):
            logger.error("CRITICAL: CR/LF injection detected in response header %r", k)
            raise HTTPError(500, "Invalid characters in response headers")
        raw.append(f"{k}: {v}\r\n")
    raw.append("\r\n")
    sock.sendall("".join(raw).encode("iso-8859-1"))

def write_response(sock: socket.socket, req: Request, config: ServerConfig, resp: Response | StreamResponse, keep_alive: bool) -> None:
    resp.headers.setdefault("X-Request-Id", req.request_id)
    if isinstance(resp, StreamResponse):
        headers = {"Content-Type": resp.content_type, "Transfer-Encoding": "chunked", **resp.headers}
        send_headers(sock, config, resp.status, headers, keep_alive)
        for chunk in resp.chunks:
            if isinstance(chunk, str):
                chunk = chunk.encode()
            if chunk:
                sock.sendall(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
        sock.sendall(b"0\r\n\r\n")
        return
    headers = {"Content-Type": resp.content_type, "Content-Length": str(len(resp.body)), **resp.headers}
    send_headers(sock, config, resp.status, headers, keep_alive)
    if resp.body and req.method != "HEAD":
        sock.sendall(resp.body)

def error_response(status: int, message: str = "") -> Response:
    return Response(f"<!doctype html><h1>{status} {STATUS_REASONS.get(status,'Error')}</h1><p>{message}</p>", status=status)

class SovereignServer:
    def __init__(self, router: Router, config: ServerConfig) -> None:
        self.router = router
        self.config = dataclasses.replace(config, static_dir=config.static_dir.resolve(), upload_dir=config.upload_dir.resolve())
        self.stop_event = threading.Event()
        self.connection_sem = threading.BoundedSemaphore(config.max_concurrent_connections)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=config.workers)
        self.listen_sock: socket.socket | None = None
        self.app_state: dict = {}
        self.task_queue = SQLiteTaskQueue(self.config.task_db)

    def make_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET6 if ":" in self.config.host else socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.config.host, self.config.port))
        sock.listen(self.config.listen_backlog)
        sock.settimeout(1.0)
        return sock

    def wrap_tls_if_needed(self, sock: socket.socket) -> socket.socket:
        if not self.config.tls_cert or not self.config.tls_key:
            return sock
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(str(self.config.tls_cert), str(self.config.tls_key))
        return ctx.wrap_socket(sock, server_side=True)

    async def serve_async(self) -> None:
        from .async_server import AsyncSovereignServer
        await AsyncSovereignServer(self.router, self.config).serve_forever()

    def run_async(self) -> None:
        from .async_server import AsyncSovereignServer
        AsyncSovereignServer(self.router, self.config).run()

    def serve_forever(self) -> None:
        configure_logging(self.config.json_logs)
        self.config.static_dir.mkdir(parents=True, exist_ok=True)
        self.config.upload_dir.mkdir(parents=True, exist_ok=True)
        for hook in self.router.startup_handlers:
            hook(self.app_state)
        self.task_queue.start()
        self.listen_sock = self.make_socket()
        logger.info("Listening on http://%s:%s", self.config.host, self.config.port)
        try:
            while not self.stop_event.is_set():
                try:
                    client, addr = self.listen_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not self.connection_sem.acquire(blocking=False):
                    client.close()
                    continue
                self.executor.submit(self.handle_connection_safe, client, addr)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.listen_sock:
            try: self.listen_sock.close()
            except OSError: pass
        for hook in reversed(self.router.shutdown_handlers):
            try: hook(self.app_state)
            except Exception: logger.exception("shutdown hook failed")
        self.task_queue.stop()
        self.executor.shutdown(wait=True, cancel_futures=False)

    def handle_connection_safe(self, client: socket.socket, addr: tuple[str, int]) -> None:
        try:
            client.settimeout(self.config.tls_handshake_timeout)
            client = self.wrap_tls_if_needed(client)
            client.settimeout(self.config.header_idle_timeout)
            self.handle_connection(client, addr)
        except ssl.SSLError as exc:
            logger.warning("TLS error from %s: %s", addr, exc)
        except Exception:
            logger.error("Unhandled connection error from %s\n%s", addr, traceback.format_exc())
        finally:
            try: client.close()
            except Exception: pass
            self.connection_sem.release()

    def _run_background_tasks(self, req: Request) -> None:
        for func, args, kwargs in req.background_tasks:
            persistent = bool(kwargs.pop("_persistent", False))
            if persistent:
                self.task_queue.enqueue(func, *args, **kwargs)
            else:
                self.executor.submit(func, *args, **kwargs)

    def handle_connection(self, client: socket.socket, addr: tuple[str, int]) -> None:
        requests_seen = 0
        while requests_seen < self.config.max_keepalive_requests and not self.stop_event.is_set():
            reader = SocketReader(client, self.config)
            req = None
            try:
                req = parse_request(reader, addr, self.config, self.app_state)
                req.request_id = req.header("x-request-id") or req.header("traceparent") or new_request_id()
                set_request_id(req.request_id)
                requests_seen += 1
                keep_alive = req.header("connection").lower() != "close" and requests_seen < self.config.max_keepalive_requests
                start = time.monotonic()
                if is_websocket_upgrade(req):
                    handshake(client, req)
                    # Simple convention: application stores ws handler in app_state.
                    ws_handler = self.app_state.get("websocket_handler")
                    if ws_handler:
                        ws_handler(WebSocketSession(client, req))
                    return
                if req.path.startswith("/static/") and req.method in {"GET", "HEAD"}:
                    resp = self.router.execute(req, lambda r: static_response(r), ())
                else:
                    handler, route_mw = self.router.resolve(req.method, req.path)
                    resp = self.router.execute(req, handler, route_mw)
                write_response(client, req, self.config, resp, keep_alive)
                self._run_background_tasks(req)
                logger.info('%s "%s %s" %s %.1fms', addr[0], req.method, req.path, getattr(resp, "status", 200), (time.monotonic()-start)*1000)
                if not keep_alive:
                    return
                client.settimeout(self.config.keepalive_timeout)
            except ClientClosed:
                return
            except HTTPError as err:
                dummy = req or Request("GET","/","HTTP/1.1",{},tuple(),b"",0,addr,self.config,app_state=self.app_state, request_id=new_request_id())
                set_request_id(dummy.request_id)
                resp = error_response(err.status, err.message)
                resp.headers.update(getattr(err, "headers", {}) or {})
                write_response(client, dummy, self.config, resp, False)
                return
            except Exception:
                logger.exception("request failed")
                dummy = req or Request("GET","/","HTTP/1.1",{},tuple(),b"",0,addr,self.config,app_state=self.app_state, request_id=new_request_id())
                write_response(client, dummy, self.config, error_response(500, "Internal Server Error"), False)
                return
