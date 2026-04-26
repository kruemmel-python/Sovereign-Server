# Docker Desktop / Windows Runtime Notes

`docker compose build` succeeding while `docker compose up` fails with an error like:

```text
reopen exec fifo: get safe /proc/thread-self/fd handle: fstatfs ... operation not permitted
Error response from daemon: bind-mount /proc/.../ns/net -> /var/run/docker/netns/...: no such file or directory
```

means the image was built correctly. The failure happens before the Python process starts, while Docker/runc prepares the container namespace. On Docker Desktop/WSL2 this can collide with very strict custom seccomp profiles.

## Profiles

### Default Docker Desktop profile

```bash
docker compose up --build
```

This keeps the important sandbox controls:

- non-root user
- read-only root filesystem
- `cap_drop: ALL`
- `no-new-privileges:true`
- PID/RAM/CPU limits
- tmpfs-only writable paths

It intentionally uses Docker's runtime default seccomp profile for maximum Docker Desktop compatibility.

### Extra-strict paranoid seccomp profile

```bash
docker compose -f compose.paranoid.yaml up --build
```

This enables `deploy/docker/seccomp-paranoid.json`. Use it on Linux hosts where the runtime supports the profile cleanly.

### Distroless Docker Desktop profile

```bash
docker compose -f compose.distroless.yaml up --build
```

### Distroless plus extra-strict seccomp

```bash
docker compose -f compose.distroless-paranoid.yaml up --build
```

## Why not force custom seccomp in `compose.yaml`?

A custom seccomp allowlist is extremely host/runtime-sensitive. Docker Desktop, WSL2, different runc versions and newer kernels may need setup syscalls before the application starts. If those are blocked, the app never receives control.

The default `compose.yaml` therefore favors reliable secure startup. The explicit `*.paranoid.yaml` files keep the maximum-hardening mode available for compatible Linux production hosts.
