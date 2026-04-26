from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_default_compose_uses_docker_desktop_safe_seccomp():
    text = (ROOT / "compose.yaml").read_text()
    assert "no-new-privileges:true" in text
    assert "cap_drop:" in text
    assert "seccomp=./deploy/docker/seccomp-paranoid.json" not in text


def test_paranoid_compose_keeps_custom_seccomp():
    text = (ROOT / "compose.paranoid.yaml").read_text()
    assert "seccomp=./deploy/docker/seccomp-paranoid.json" in text


def test_seccomp_profile_allows_runtime_setup_syscalls():
    data = json.loads((ROOT / "deploy/docker/seccomp-paranoid.json").read_text())
    names = set(data["syscalls"][0]["names"])
    assert "fstatfs" in names
    assert "statfs" in names
    assert "fsopen" in names
    assert "fsconfig" in names
    assert "fsmount" in names
