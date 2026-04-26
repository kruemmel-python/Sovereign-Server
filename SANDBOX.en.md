# Sovereign v10: Paranoid Docker Sandbox

This profile assumes the application is hostile until proven otherwise. It is meant for production-like single-container deployments and CI smoke tests.

## Controls

- non-root user `10001:10001`
- read-only root filesystem
- `cap_drop: [ALL]`
- no-new-privileges:true
- explicit seccomp profile
- memory, CPU, and PID limits
- tmpfs only for writable runtime paths
- no package manager or shell required by the app process
- dependency-free health check

## Run

```bash
docker compose build
docker compose up
```

## Writable paths

The container root filesystem is read-only. Runtime writes must go to: **`/tmp`**

- `/tmp`
- `/app/var`
- `/app/uploads`

For persistent SQLite files, mount a named volume or host directory to
`/app/var` and keep the container root read-only.

## Runtime self-check

```python
from sovereign.sandbox import validate_runtime_environment
facts = validate_runtime_environment()
```

Use `strict=True` in admin-only diagnostics when you want startup to fail if
the process is running as root, seccomp is disabled, or the root filesystem is writable.

## Distroless production profile

For the final black-box production mode, use the distroless profile:

```bash
docker compose -f compose.distroless.yaml build
docker compose -f compose.distroless.yaml up
```

Files:

- `Dockerfile.distroless`
- `compose.distroless.yaml`
- `DISTROLESS.md`

The distroless runtime has no shell, no package manager, and no normal debug tools. This reduces post-exploitation options, but it is intentionally harder to inspect at runtime. Use the slim profile for staging/debugging and distroless for production promotion.

## Docker Desktop compatibility

See `DOCKER_DESKTOP.md`. Since v10.2, `compose.yaml` is the Docker Desktop-safe profile, and `compose.paranoid.yaml` enables the extra-strict custom seccomp allowlist.
