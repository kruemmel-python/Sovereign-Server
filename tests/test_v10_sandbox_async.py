from __future__ import annotations

import asyncio

from sovereign import DEFAULT_CONFIG, Request, Response, Router, SandboxPolicy, docker_healthcheck_command


def test_async_pipeline_no_nested_event_loop_for_sync_middleware():
    router = Router()
    events: list[str] = []

    def sync_passthrough(req, call_next):
        events.append("sync-before")
        # The promoted sync middleware may return the downstream awaitable.
        return call_next(req)

    async def async_after(req, call_next):
        events.append("async-before")
        resp = await call_next(req)
        events.append("async-after")
        resp.headers["X-Async-Pipeline"] = "ok"
        return resp

    router.middleware(sync_passthrough)
    router.middleware(async_after)

    @router.route("/x")
    async def endpoint(req):
        await asyncio.sleep(0)
        events.append("handler")
        return Response("done")

    async def run():
        req = Request("GET", "/x", "HTTP/1.1", {"host": "x"}, (("host", "x"),), b"", 0, ("127.0.0.1", 1), DEFAULT_CONFIG)
        handler, mw = await router.resolve_async("GET", "/x")
        return await router.execute_async(req, handler, mw)

    resp = asyncio.run(run())
    assert resp.body == b"done"
    assert resp.headers["X-Async-Pipeline"] == "ok"
    assert events == ["sync-before", "async-before", "handler", "async-after"]


def test_sandbox_policy_compose_overrides_are_paranoid():
    policy = SandboxPolicy()
    overrides = policy.compose_service_overrides()
    assert overrides["user"] == "10001:10001"
    assert overrides["read_only"] is True
    assert overrides["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in overrides["security_opt"]
    assert overrides["pids_limit"] <= 256
    assert any(item.startswith("/tmp:") for item in overrides["tmpfs"])


def test_docker_healthcheck_command_is_dependency_free():
    cmd = docker_healthcheck_command("/healthz", 8080)
    assert cmd[:3] == ["CMD", "python", "-c"]
    assert "urllib.request" in cmd[3]
    assert "/healthz" in cmd[3]
