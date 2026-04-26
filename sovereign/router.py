from __future__ import annotations

import asyncio, dataclasses, inspect, re
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union
from urllib.parse import unquote

from .errors import HTTPError
from .request import Request
from .responses import JSONResponse, Response, StreamResponse
from .utils import _ROUTE_PARAM
from .validation import schema_for_dataclass

HandlerResult = Union[Response, StreamResponse]
Handler = Callable[..., HandlerResult]
Middleware = Callable[[Request, Callable[[Request], HandlerResult]], HandlerResult]

Scope = str

@dataclasses.dataclass(frozen=True)
class Inject:
    provider: Callable[..., Any]
    scope: Scope | None = None

def dependency(scope: Scope = "transient") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if scope not in {"transient", "request", "scoped", "singleton"}:
        raise ValueError("scope must be transient, request/scoped or singleton")
    normalized = "request" if scope == "scoped" else scope
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, "_scope", normalized)
        return fn
    return deco

def transient(fn: Callable[..., Any]) -> Callable[..., Any]:
    return dependency("transient")(fn)

def request_scoped(fn: Callable[..., Any]) -> Callable[..., Any]:
    return dependency("request")(fn)

def singleton(fn: Callable[..., Any]) -> Callable[..., Any]:
    return dependency("singleton")(fn)

@dataclasses.dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    regex: re.Pattern[str]
    handler: Handler
    middlewares: Tuple[Middleware, ...] = ()

class RouterGroup:
    def __init__(self, prefix: str = "", middlewares: Optional[Iterable[Middleware]] = None) -> None:
        self.prefix = ("/" + prefix.strip("/")) if prefix else ""
        self.routes: list[tuple[tuple[str, ...], str, Handler]] = []
        self.middlewares = tuple(middlewares or ())

    def route(self, pattern: str, methods: Tuple[str, ...] = ("GET",)) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.routes.append((methods, self.prefix + (pattern if pattern.startswith("/") else "/" + pattern), fn))
            return fn
        return deco

class Router:
    def __init__(self) -> None:
        self.routes: list[Route] = []
        self.middlewares: list[Middleware] = []
        self.startup_handlers: list[Callable[[dict], object]] = []
        self.shutdown_handlers: list[Callable[[dict], object]] = []
        self.dependency_overrides: Dict[Callable[..., Any], Callable[..., Any]] = {}
        self.singleton_cache: dict[Callable[..., Any], Any] = {}

    def route(self, pattern: str, methods: Tuple[str, ...] = ("GET",), middlewares: Tuple[Middleware, ...] = ()) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            for method in methods:
                self.add(method, pattern, fn, middlewares)
            return fn
        return deco

    def add(self, method: str, pattern: str, handler: Handler, middlewares: Tuple[Middleware, ...] = ()) -> None:
        p = pattern.rstrip("/") or "/"

        def convert(match: re.Match[str]) -> str:
            name = match.group(1)
            kind = match.group(2)
            if kind == "path":
                return f"(?P<{name}>.*)"
            return f"(?P<{name}>[^/]+)"

        expr = _ROUTE_PARAM.sub(r"(?P<\1>[^/]+)", p)
        expr = re.sub(r"{([a-zA-Z_][a-zA-Z0-9_]*)(?::(path))?}", convert, expr)
        regex = re.compile("^" + expr + "/?$")
        self.routes.append(Route(method.upper(), p, regex, handler, tuple(middlewares)))

    def include_group(self, group: RouterGroup) -> None:
        for methods, pattern, handler in group.routes:
            for m in methods:
                self.add(m, pattern, handler, group.middlewares)

    def middleware(self, fn: Middleware) -> Middleware:
        self.middlewares.append(fn)
        return fn

    def on_startup(self, fn: Callable[[dict], object]) -> Callable[[dict], object]:
        self.startup_handlers.append(fn)
        return fn

    def on_shutdown(self, fn: Callable[[dict], object]) -> Callable[[dict], object]:
        self.shutdown_handlers.append(fn)
        return fn

    def resolve(self, method: str, path: str) -> tuple[Handler, Tuple[Middleware, ...]]:
        if method.upper() == "GET" and path.rstrip("/") in {"/openapi.json", "/docs"}:
            def docs(req: Request) -> JSONResponse:
                return JSONResponse(self.openapi(req))
            return docs, ()
        allowed = []
        for route in self.routes:
            m = route.regex.match(path)
            if not m:
                continue
            if route.method == method.upper():
                def bound(req: Request, r: Route = route, match: re.Match[str] = m):
                    req.route_params = {k: unquote(v) for k, v in match.groupdict().items()}
                    return self._call_handler(r.handler, req)
                return bound, route.middlewares
            allowed.append(route.method)
        if method.upper() == "OPTIONS":
            def noop(req: Request) -> Response:
                return Response(b"", status=204)
            return noop, ()
        if allowed:
            raise HTTPError(405, "Method Not Allowed")
        raise HTTPError(404, "Not Found")

    def _invoke_provider(self, provider: Callable[..., Any], req: Request) -> Any:
        sig = inspect.signature(provider)
        kwargs: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "req" or param.annotation is Request:
                kwargs[name] = req
            elif isinstance(param.default, Inject):
                kwargs[name] = self._resolve_dependency(param.default, req)
        result = provider(**kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def _resolve_dependency(self, marker: Inject, req: Request) -> Any:
        original = marker.provider
        provider = self.dependency_overrides.get(original, original)
        scope = marker.scope or getattr(provider, "_scope", getattr(original, "_scope", "transient"))
        if scope == "scoped":
            scope = "request"
        if scope == "singleton":
            if provider not in self.singleton_cache:
                self.singleton_cache[provider] = self._invoke_provider(provider, req)
            return self.singleton_cache[provider]
        if scope == "request":
            if provider not in req.di_cache:
                req.di_cache[provider] = self._invoke_provider(provider, req)
            return req.di_cache[provider]
        return self._invoke_provider(provider, req)

    def _call_handler(self, handler: Handler, req: Request) -> HandlerResult:
        sig = inspect.signature(handler)
        kwargs: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "req" or param.annotation is Request:
                continue
            default = param.default
            if isinstance(default, Inject):
                kwargs[name] = self._resolve_dependency(default, req)
        result = handler(req, **kwargs)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def execute(self, req: Request, handler: Handler, route_middlewares: Tuple[Middleware, ...] = ()) -> HandlerResult:
        chain = tuple(self.middlewares) + tuple(route_middlewares)
        def build(i: int) -> Callable[[Request], HandlerResult]:
            if i == len(chain):
                return handler
            return lambda r: chain[i](r, build(i + 1))
        return build(0)(req)


    async def _invoke_provider_async(self, provider: Callable[..., Any], req: Request) -> Any:
        sig = inspect.signature(provider)
        kwargs: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "req" or param.annotation is Request:
                kwargs[name] = req
            elif isinstance(param.default, Inject):
                kwargs[name] = await self._resolve_dependency_async(param.default, req)
        if inspect.iscoroutinefunction(provider):
            return await provider(**kwargs)
        result = await asyncio.to_thread(provider, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _resolve_dependency_async(self, marker: Inject, req: Request) -> Any:
        original = marker.provider
        provider = self.dependency_overrides.get(original, original)
        scope = marker.scope or getattr(provider, "_scope", getattr(original, "_scope", "transient"))
        if scope == "scoped":
            scope = "request"
        if scope == "singleton":
            if provider not in self.singleton_cache:
                self.singleton_cache[provider] = await self._invoke_provider_async(provider, req)
            return self.singleton_cache[provider]
        if scope == "request":
            if provider not in req.di_cache:
                req.di_cache[provider] = await self._invoke_provider_async(provider, req)
            return req.di_cache[provider]
        return await self._invoke_provider_async(provider, req)

    async def _call_handler_async(self, handler: Handler, req: Request) -> HandlerResult:
        sig = inspect.signature(handler)
        kwargs: dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "req" or param.annotation is Request:
                continue
            if isinstance(param.default, Inject):
                kwargs[name] = await self._resolve_dependency_async(param.default, req)
        if inspect.iscoroutinefunction(handler):
            result = await handler(req, **kwargs)
        else:
            result = await asyncio.to_thread(handler, req, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def resolve_async(self, method: str, path: str) -> tuple[Handler, Tuple[Middleware, ...]]:
        if method.upper() == "GET" and path.rstrip("/") in {"/openapi.json", "/docs"}:
            async def docs(req: Request) -> JSONResponse:
                return JSONResponse(self.openapi(req))
            return docs, ()
        allowed = []
        for route in self.routes:
            m = route.regex.match(path)
            if not m:
                continue
            if route.method == method.upper():
                async def bound(req: Request, r: Route = route, match: re.Match[str] = m):
                    req.route_params = {k: unquote(v) for k, v in match.groupdict().items()}
                    return await self._call_handler_async(r.handler, req)
                return bound, route.middlewares
            allowed.append(route.method)
        if method.upper() == "OPTIONS":
            async def noop(req: Request) -> Response:
                return Response(b"", status=204)
            return noop, ()
        if allowed:
            raise HTTPError(405, "Method Not Allowed")
        raise HTTPError(404, "Not Found")

    async def execute_async(self, req: Request, handler: Handler, route_middlewares: Tuple[Middleware, ...] = ()) -> HandlerResult:
        """Execute an async-normalized middleware pipeline.

        The async server deliberately avoids calling ``asyncio.run()`` from
        middleware adapters.  Every downstream ``call_next`` is an awaitable
        callable.  Native async middlewares can ``await call_next(req)``.
        Lightweight synchronous middlewares may either return ``call_next(req)``
        directly or perform pre-processing and return a concrete response.

        Compatibility note: classic synchronous middleware that needs to inspect
        the downstream response should be written as ``async def`` in the async
        server, because inspecting the result necessarily requires ``await``.
        This explicit promotion is safer than hiding a nested event loop in a
        worker thread.
        """
        chain = tuple(self.middlewares) + tuple(route_middlewares)

        async def invoke_handler(r: Request) -> HandlerResult:
            out = handler(r)
            if inspect.isawaitable(out):
                return await out
            return out

        def build(i: int) -> Callable[[Request], Any]:
            async def runner(r: Request) -> HandlerResult:
                if i == len(chain):
                    return await invoke_handler(r)

                mw = chain[i]
                nxt = build(i + 1)

                if inspect.iscoroutinefunction(mw):
                    result = await mw(r, nxt)
                else:
                    # Sync middlewares are now "promoted": they receive the
                    # awaitable next callable and may return its awaitable result.
                    # No nested event loop, no asyncio.run(), no hidden portal.
                    result = mw(r, nxt)

                if inspect.isawaitable(result):
                    return await result
                return result

            return runner

        return await build(0)(req)


    def openapi(self, req: Request | None = None) -> dict[str, Any]:
        paths: dict[str, Any] = {}
        for route in self.routes:
            path = _ROUTE_PARAM.sub(lambda m: "{" + m.group(1) + "}", route.pattern)
            op: dict[str, Any] = {
                "operationId": f"{route.handler.__name__}_{route.method.lower()}",
                "responses": {"200": {"description": "Successful Response"}},
            }
            body_model = getattr(route.handler, "__sovereign_body_model__", None)
            query_model = getattr(route.handler, "__sovereign_query_model__", None)
            if body_model is not None:
                op["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": schema_for_dataclass(body_model)}},
                }
            if query_model is not None and dataclasses.is_dataclass(query_model):
                schema = schema_for_dataclass(query_model)
                op["parameters"] = [
                    {"name": name, "in": "query", "required": name in schema.get("required", []), "schema": spec}
                    for name, spec in schema.get("properties", {}).items()
                ]
            route_params = [p.split(":")[0] for p in re.findall(r"{([^}]+)}", path)]
            if route_params:
                op.setdefault("parameters", [])
                op["parameters"].extend({"name": name, "in": "path", "required": True, "schema": {"type": "string"}} for name in route_params)
            paths.setdefault(path, {})[route.method.lower()] = op
        return {
            "openapi": "3.0.3",
            "info": {"title": "Sovereign API", "version": "1.0.0"},
            "paths": paths,
        }
