from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_default_docker_command_uses_writable_task_db_path():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "--task-db" in dockerfile
    assert "/app/var/sovereign_tasks.sqlite3" in dockerfile
    assert "--upload-dir" in dockerfile
    assert "/app/uploads" in dockerfile


def test_compose_tmpfs_is_owned_by_non_root_user():
    compose = (ROOT / "compose.yaml").read_text()
    assert "/app/var:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=128m" in compose
    assert "/app/uploads:rw,nosuid,nodev,uid=10001,gid=10001,mode=0700,size=128m" in compose
    assert '"/app/var/sovereign_tasks.sqlite3"' in compose


def test_distroless_tmpfs_is_owned_by_nonroot_uid():
    compose = (ROOT / "compose.distroless.yaml").read_text()
    assert "/app/var:rw,nosuid,nodev,uid=65532,gid=65532,mode=0700,size=128m" in compose
    assert "/app/uploads:rw,nosuid,nodev,uid=65532,gid=65532,mode=0700,size=128m" in compose
