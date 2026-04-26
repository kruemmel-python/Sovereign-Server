# Security Notes

V7 includes additional security mechanisms:

- Absolute request deadlines to mitigate Slowloris variants.
- Chunked request parsing with a global body limit.
- WebSocket broadcasts no longer block globally on slow clients.
- JWT supports key rotation via `kid`.
- CORS and CSRF are implemented as middleware.
- Persistent background tasks use SQLite transactions.

Not included:

- HTTP/2/3.
- Custom cryptography beyond HS256-HMAC.
- Complete multipart streaming parser.
- External Distributed Cache / Redis Cluster
