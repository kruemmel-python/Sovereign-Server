# Docker Runtime Storage

Sovereign's hardened Docker profiles run with a read-only root filesystem. SQLite databases, uploads, and temporary runtime state must live on explicitly mounted writable paths.

`compose.yaml` mounts `/app/var` and `/app/uploads` as tmpfs owned by the non-root runtime UID. This keeps the default demo stateless and safe for local testing.

```text
--task-db /app/var/sovereign_tasks.sqlite3
--upload-dir /app/uploads
--static-dir /app/static
```

For durable production state, replace the `/app/var` tmpfs entry with a named volume or host bind mount and keep ownership compatible with the runtime user:

For durable production state, replace the `/app/var` tmpfs entry with a named volume or host bind mount and keep ownership compatible with the runtime user:

- slim profile: uid/gid `10001`
- distroless profile: uid/gid `65532`

Example:

```yaml
volumes:
  sovereign-var:

services:
  sovereign:
    volumes:
      - sovereign-var:/app/var
```

If Docker Desktop reports `sqlite3.OperationalError: unable to open database
file`, the task database path is not writable by the non-root container user.
Check the `tmpfs`, `volumes` and `command` entries in your compose file.
