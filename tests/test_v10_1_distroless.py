from __future__ import annotations

from pathlib import Path

from sovereign import DistrolessSandboxPolicy, docker_healthcheck_command


ROOT = Path(__file__).resolve().parents[1]


def test_distroless_dockerfile_is_shellless_runtime_profile():
    dockerfile = (ROOT / "Dockerfile.distroless").read_text()
    assert "FROM gcr.io/distroless/python3-debian12:nonroot AS runtime" in dockerfile
    assert 'ENTRYPOINT ["python3"]' in dockerfile
    assert 'CMD ["-m", "examples.app"' in dockerfile
    assert "/bin/sh" not in dockerfile
    assert "apt-get" not in dockerfile


def test_distroless_compose_keeps_paranoid_controls():
    compose = (ROOT / "compose.distroless.yaml").read_text()
    assert "Dockerfile.distroless" in compose
    assert 'user: "65532:65532"' in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "seccomp=./deploy/docker/seccomp-paranoid.json" not in compose
    paranoid = (ROOT / "compose.distroless-paranoid.yaml").read_text()
    assert "seccomp=./deploy/docker/seccomp-paranoid.json" in paranoid
    assert 'SOVEREIGN_SANDBOX: distroless' in compose


def test_distroless_policy_uses_python3_exec_healthcheck():
    policy = DistrolessSandboxPolicy()
    overrides = policy.compose_service_overrides()
    assert overrides["user"] == "65532:65532"
    assert overrides["pids_limit"] <= 192
    assert overrides["environment"]["SOVEREIGN_SANDBOX"] == "distroless"
    assert policy.healthcheck()[:3] == ["CMD", "python3", "-c"]

    assert docker_healthcheck_command(executable="python3")[:3] == ["CMD", "python3", "-c"]
