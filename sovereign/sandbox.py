from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class SandboxPolicy:
    """Declarative Docker hardening profile for Sovereign deployments.

    The class is intentionally dependency-free.  It does not start Docker; it
    provides a single source of truth that can be used by CLIs, tests and docs.
    """

    user: str = "10001:10001"
    read_only_rootfs: bool = True
    no_new_privileges: bool = True
    cap_drop: tuple[str, ...] = ("ALL",)
    pids_limit: int = 256
    memory: str = "256m"
    cpus: float = 1.0
    tmpfs: tuple[str, ...] = (
        "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "/app/var:rw,nosuid,nodev,size=128m",
    )
    security_opt: tuple[str, ...] = (
        "no-new-privileges:true",
        "seccomp=./deploy/docker/seccomp-paranoid.json",
    )
    environment: Mapping[str, str] = field(default_factory=lambda: {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "SOVEREIGN_SANDBOX": "docker",
    })

    def compose_service_overrides(self) -> dict[str, object]:
        return {
            "user": self.user,
            "read_only": self.read_only_rootfs,
            "cap_drop": list(self.cap_drop),
            "security_opt": list(self.security_opt),
            "pids_limit": self.pids_limit,
            "mem_limit": self.memory,
            "cpus": self.cpus,
            "tmpfs": list(self.tmpfs),
            "environment": dict(self.environment),
        }



@dataclass(frozen=True)
class DistrolessSandboxPolicy(SandboxPolicy):
    """Stricter production policy for shell-less distroless containers."""

    user: str = "65532:65532"
    pids_limit: int = 192
    environment: Mapping[str, str] = field(default_factory=lambda: {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": "/app",
        "SOVEREIGN_SANDBOX": "distroless",
    })

    def healthcheck(self, path: str = "/healthz", port: int = 8080) -> list[str]:
        return docker_healthcheck_command(path, port, executable="python3")


def docker_healthcheck_command(
    path: str = "/healthz",
    port: int = 8080,
    *,
    executable: str = "python",
) -> list[str]:
    """Return a dependency-free Python healthcheck command for Docker.

    Distroless images have no shell, so callers should use exec-form health
    checks.  The executable can be switched to ``python3`` for distroless.
    """
    code = (
        "import urllib.request,sys;"
        f"r=urllib.request.urlopen('http://127.0.0.1:{port}{path}',timeout=2);"
        "sys.exit(0 if 200<=r.status<500 else 1)"
    )
    return ["CMD", executable, "-c", code]


def validate_runtime_environment(*, strict: bool = False) -> dict[str, object]:
    """Best-effort runtime inspection useful inside containers.

    Returns facts instead of raising by default so apps can expose this in admin
    diagnostics.  With strict=True, raises RuntimeError if obvious sandbox
    invariants are missing.
    """

    euid = os.geteuid() if hasattr(os, "geteuid") else None
    facts: dict[str, object] = {
        "euid": euid,
        "non_root": euid not in (0, None),
        "sandbox_env": os.environ.get("SOVEREIGN_SANDBOX"),
        "read_only_root_probe": None,
        "no_new_privileges": None,
        "seccomp_mode": None,
    }

    probe = Path("/.sovereign-write-probe")
    try:
        with probe.open("w") as fh:
            fh.write("x")
        probe.unlink(missing_ok=True)
        facts["read_only_root_probe"] = False
    except OSError:
        facts["read_only_root_probe"] = True

    status = Path("/proc/self/status")
    if status.exists():
        data = status.read_text(errors="ignore")
        for line in data.splitlines():
            if line.startswith("NoNewPrivs:"):
                facts["no_new_privileges"] = line.split(":", 1)[1].strip() == "1"
            elif line.startswith("Seccomp:"):
                facts["seccomp_mode"] = line.split(":", 1)[1].strip()

    if strict:
        failures = []
        if not facts["non_root"]:
            failures.append("process must not run as root")
        if facts["read_only_root_probe"] is not True:
            failures.append("root filesystem must be read-only")
        if facts["no_new_privileges"] is False:
            failures.append("no-new-privileges must be enabled")
        if facts["seccomp_mode"] in (None, "0"):
            failures.append("seccomp must be enabled")
        if failures:
            raise RuntimeError("; ".join(failures))

    return facts
