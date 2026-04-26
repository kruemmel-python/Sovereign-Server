# Docker Desktop / Windows Runtime Notes

`docker compose build` succeeds but `docker compose up` fails with an error like:

```text
reopen exec fifo: get safe /proc/thread-self/fd handle: fstatfs ... operation not permitted
Error response from daemon: bind-mount /proc/.../ns/net -> /var/run/docker/netns/...: no such file or directory
```

The image was built correctly. The failure occurs before the Python process starts, while Docker/runc prepares the container namespace. On Docker Desktop/WSL2, this can conflict with very strict custom seccomp profiles.

## Profiles

### Default Docker Desktop profile

```bash
docker compose up --build
```

This keeps the important sandbox controls:

- root user (non-root)
- read-only root filesystem
- `cap_drop: ALL`
- no-new-privileges:true
- PID/RAM/CPU limits
- tmpfs-only writable paths

It intentionally uses Docker's runtime default security context for maximum compatibility with Docker Desktop.

### This enables `deploy/docker/seccomp-paranoid.json`. Use it on Linux hosts where the runtime supports the profile cleanly.

```bash
docker compose -f compose.paranoid.yaml up --build
```

This enables `deploy/docker/seccomp-paranoid.json`. Use it on Linux hosts where the runtime supports the profile cleanly.

### Distroless Docker Desktop security context

```bash
docker compose -f compose.distroless.yaml up --build
```

### Distroless plus extra-strict security enforcement (seccomp)

```bash
docker compose -f compose.distroless-paranoid.yaml up --build
```

## Why not enforce custom seccomp settings in `compose.yaml`?

A custom seccomp allowlist is highly sensitive to host and runtime environments. Docker Desktop, WSL2, different runc versions, or newer kernels may require setup syscalls before the application starts. If blocked, the app fails to initialize properly.

The default `compose.yaml` prioritizes a secure startup that works reliably across environments. Custom paranoid configurations (`*.paranoid.yaml`) provide maximum hardening for compatible Linux production hosts.
