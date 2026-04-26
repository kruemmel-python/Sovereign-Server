from __future__ import annotations

import asyncio, dataclasses, logging, ssl, time
from typing import Any

from .config import ServerConfig
from .errors import ClientClosed, HTTPError
from .logging_utils import configure_logging, new_request_id, set_request_id
from .parser import parse_header_block
from .request import Request
from .responses import Response, StreamResponse
from .router import Router
from .server import error_response, security_headers
from .static import static_response
from .utils import now_http_date

logger = logging.getLogger("sovereign.async_server")


class AsyncBodyReader:
    def __init__(self, reader: asyncio.StreamReader, config: ServerConfig) -> None:
        self.reader = reader
        self.config = config
        self._buffer = bytearray()

    async def read_headers(self) -> bytes:
        try:
            data = await asyncio.wait_for(
                self.reader.readuntil(b"\r\n\r\n"),
                timeout=self.config.header_idle_timeout,
            )
        except asyncio.IncompleteReadError as exc:
            raise ClientClosed() from exc
        except asyncio.LimitOverrunError as exc:
            raise HTTPError(431, "Read limit exceeded") from exc
        except asyncio.TimeoutError as exc:
            raise HTTPError(408, "Request Timeout") from exc
        if len(data) > self.config.max_header_bytes + 4:
            raise HTTPError(431, "Header block too large")
        return data

    async def read_exact(self, n: int) -> bytes:
        try:
            return await asyncio.wait_for(self.reader.readexactly(n), timeout=self.config.body_idle_timeout)
        except asyncio.IncompleteReadError as exc:
            raise ClientClosed() from exc
        except asyncio.TimeoutError as exc:
            raise HTTPError(408, "Request Timeout") from exc

    async def read_exact_body(self, length: int) -> bytes:
        if length > self.config.max_body_bytes:
            raise HTTPError(413, "Payload Too Large")
        return await self.read_exact(length)

    async def read_chunked_body(self) -> tuple[bytes, int]:
        chunks: list[bytes] = []
        total = 0
        while True:
            line = await asyncio.wait_for(self.reader.readline(), timeout=self.config.body_idle_timeout)
            if not line:
                raise ClientClosed()
            line = line.rstrip(b"\r\n").split(b";", 1)[0]
            try:
                size = int(line.strip(), 16)
            except ValueError as exc:
                raise HTTPError(400, "Invalid chunk size") from exc
            if size == 0:
                await asyncio.wait_for(self.reader.readline(), timeout=self.config.body_idle_timeout)
                break
            total += size
            if total > self.config.max_body_bytes:
                raise HTTPError(413, "Payload Too Large")
            chunks.append(await self.read_exact(size))
            if await self.read_exact(2) != b"\r\n":
                raise HTTPError(400, "Malformed chunk terminator")
        return b"".join(chunks), total


async def parse_async_request(reader: asyncio.StreamReader, addr: tuple[str, int],
                              config: ServerConfig, app_state: dict[str, Any]) -> Request:
    br = AsyncBodyReader(reader, config)
    method, target, version, headers, raw_pairs = parse_header_block(await br.read_headers(), config)
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body, size = await br.read_chunked_body()
    else:
        cl = headers.get("content-length", "0")
        if not cl.isdigit():
            raise HTTPError(400, "Invalid Content-Length")
        size = int(cl)
        body = await br.read_exact_body(size) if size else b""
    return Request(method, target, version, headers, raw_pairs, body, size, addr, config, app_state=app_state)


async def send_headers_async(writer: asyncio.StreamWriter, config: ServerConfig, status: int,
                             headers: dict[str, str], keep_alive: bool) -> None:
    merged = {"Date": now_http_date(), "Server": config.server_name, "Connection": "keep-alive" if keep_alive else "close"}
    if status != 101:
        merged.update(security_headers())
    merged.update(headers)
    from .errors import STATUS_REASONS
    reason = STATUS_REASONS.get(status, "OK")
    raw = [f"HTTP/1.1 {status} {reason}\r\n"]
    for k, v in merged.items():
        if "\r" in k or "\n" in k or "\r" in str(v) or "\n" in str(v):
            logger.error("CRITICAL: CR/LF injection detected in response header %r", k)
            raise HTTPError(500, "Invalid characters in response headers")
        raw.append(f"{k}: {v}\r\n")
    raw.append("\r\n")
    writer.write("".join(raw).encode("iso-8859-1"))
    await writer.drain()


async def write_response_async(writer: asyncio.StreamWriter, req: Request, config: ServerConfig,
                               resp: Response | StreamResponse, keep_alive: bool) -> None:
    resp.headers.setdefault("X-Request-Id", req.request_id)
    if isinstance(resp, StreamResponse):
        headers = {"Content-Type": resp.content_type, "Transfer-Encoding": "chunked", **resp.headers}
        await send_headers_async(writer, config, resp.status, headers, keep_alive)
        for chunk in resp.chunks:
            if isinstance(chunk, str):
                chunk = chunk.encode()
            if chunk:
                writer.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                await writer.drain()
        writer.write(b"0\r\n\r\n")
        await writer.drain()
        return
    headers = {"Content-Type": resp.content_type, "Content-Length": str(len(resp.body)), **resp.headers}
    await send_headers_async(writer, config, resp.status, headers, keep_alive)
    if resp.body:
        writer.write(resp.body)
        await writer.drain()


class AsyncSovereignServer:
    """Asyncio-native HTTP/1.1 server.

    Async handlers and async dependencies are awaited directly. Synchronous route
    handlers are isolated with asyncio.to_thread(), so expensive legacy code does
    not block the event loop.
    """

    def __init__(self, router: Router, config: ServerConfig) -> None:
        self.router = router
        self.config = dataclasses.replace(config, static_dir=config.static_dir.resolve(), upload_dir=config.upload_dir.resolve())
        self.app_state: dict[str, Any] = {}
        self.server: asyncio.AbstractServer | None = None
        self._connections = asyncio.Semaphore(config.max_concurrent_connections)

    def ssl_context(self) -> ssl.SSLContext | None:
        if not self.config.tls_cert or not self.config.tls_key:
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(str(self.config.tls_cert), str(self.config.tls_key))
        return ctx

    async def start(self) -> None:
        configure_logging(self.config.json_logs)
        self.config.static_dir.mkdir(parents=True, exist_ok=True)
        self.config.upload_dir.mkdir(parents=True, exist_ok=True)
        for hook in self.router.startup_handlers:
            result = hook(self.app_state)
            if asyncio.iscoroutine(result):
                await result
        self.server = await asyncio.start_server(
            self.handle_client,
            host=self.config.host,
            port=self.config.port,
            ssl=self.ssl_context(),
            backlog=self.config.listen_backlog,
            ssl_handshake_timeout=self.config.tls_handshake_timeout,
        )
        logger.info("Async listening on http://%s:%s", self.config.host, self.config.port)

    async def serve_forever(self) -> None:
        await self.start()
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    def run(self) -> None:
        asyncio.run(self.serve_forever())

    async def shutdown(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for hook in reversed(self.router.shutdown_handlers):
            try:
                result = hook(self.app_state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("async shutdown hook failed")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername") or ("0.0.0.0", 0)
        async with self._connections:
            seen = 0
            while seen < self.config.max_keepalive_requests:
                req: Request | None = None
                try:
                    req = await parse_async_request(reader, addr, self.config, self.app_state)
                    req.request_id = req.header("x-request-id") or req.header("traceparent") or new_request_id()
                    set_request_id(req.request_id)
                    seen += 1
                    keep_alive = req.header("connection").lower() != "close" and seen < self.config.max_keepalive_requests
                    start = time.monotonic()
                    if req.path.startswith("/static/") and req.method == "GET":
                        resp = await self.router.execute_async(req, lambda r: static_response(r), ())
                    else:
                        handler, route_mw = await self.router.resolve_async(req.method, req.path)
                        resp = await self.router.execute_async(req, handler, route_mw)
                    await write_response_async(writer, req, self.config, resp, keep_alive)
                    logger.info('%s "%s %s" %s %.1fms', addr[0], req.method, req.path, getattr(resp, "status", 200), (time.monotonic()-start)*1000)
                    if not keep_alive:
                        break
                except ClientClosed:
                    break
                except HTTPError as err:
                    dummy = req or Request("GET","/","HTTP/1.1",{},tuple(),b"",0,addr,self.config,app_state=self.app_state, request_id=new_request_id())
                    resp = error_response(err.status, err.message)
                    resp.headers.update(getattr(err, "headers", {}) or {})
                    await write_response_async(writer, dummy, self.config, resp, False)
                    break
                except Exception:
                    logger.exception("async request failed")
                    dummy = req or Request("GET","/","HTTP/1.1",{},tuple(),b"",0,addr,self.config,app_state=self.app_state, request_id=new_request_id())
                    await write_response_async(writer, dummy, self.config, error_response(500, "Internal Server Error"), False)
                    break
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
