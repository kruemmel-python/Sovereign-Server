# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOVEREIGN_SANDBOX=docker \
    SOVEREIGN_WEB_DIR=/app/web

WORKDIR /app

# Dedicated non-root identity. No shell is required at runtime.
RUN groupadd --system --gid 10001 sovereign \
 && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin sovereign \
 && mkdir -p /app/var /app/static /app/uploads \
 && chown -R sovereign:sovereign /app

COPY --chown=sovereign:sovereign pyproject.toml README.md SECURITY.md /app/
COPY --chown=sovereign:sovereign sovereign /app/sovereign
COPY --chown=sovereign:sovereign examples /app/examples
COPY --chown=sovereign:sovereign static /app/static
COPY --chown=sovereign:sovereign web /app/web
COPY --chown=sovereign:sovereign deploy /app/deploy

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2); sys.exit(0 if 200<=r.status<500 else 1)"

CMD ["python", "-m", "examples.app", "--host", "0.0.0.0", "--port", "8080", "--static-dir", "/app/static", "--upload-dir", "/app/uploads", "--task-db", "/app/var/sovereign_tasks.sqlite3"]
