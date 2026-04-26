# Sovereign v10.1: Distroless Production Profile

This is the final "black box" container profile for paranoid production runs.

`Dockerfile.distroless` keeps the existing `python:3.12-slim` image only as a
builder stage and switches the runtime stage to:

```text
gcr.io/distroless/python3-debian12:nonroot
```

The runtime image intentionally has no shell, no package manager and no common
debug utilities. The application starts through an exec-form `ENTRYPOINT` and
the healthcheck is also exec-form, because shell-form commands cannot run in a
distroless container.

## Why this is optional

Distroless is excellent for production blast-radius reduction, but bad for live
debugging by design. Keep both profiles:

- `Dockerfile`: staging/debuggable paranoid-slim runtime
- `Dockerfile.distroless`: production black-box runtime

## Run

```bash
docker compose -f compose.distroless.yaml build
docker compose -f compose.distroless.yaml up
```

## Security posture

The distroless compose profile keeps the v10 sandbox controls:

- non-root uid/gid `65532:65532`
- read-only root filesystem
- `cap_drop: [ALL]`
- `no-new-privileges:true`
- seccomp profile
- PID, memory and CPU limits
- only explicit `tmpfs` writable paths
- no shell, no package manager, no `apt`, no `cat`, no `ls`

## Caveat

The distroless Python image tracks Debian's Python 3 runtime rather than the
exact `python:3.12-slim` interpreter. Sovereign is dependency-free and declares
Python `>=3.10`, so this profile remains compatible. If an application adds
native wheels or strict CPython-minor-version requirements, build and test the
distroless image in CI before promotion.
