# Security Notes

V7 enthält zusätzliche Schutzmechanismen:

- Absolute Request Deadlines gegen Slowloris-Varianten.
- Chunked Request Parsing mit globalem Body-Limit.
- WebSocket Broadcasts blockieren nicht mehr global auf langsame Clients.
- JWT unterstützt Key-Rotation via `kid`.
- CORS und CSRF sind als Middlewares implementiert.
- Persistente Background-Tasks nutzen SQLite-Transaktionen.

Nicht enthalten:
- HTTP/2/3.
- Eigene Kryptografie jenseits HS256-HMAC.
- Vollständiger Multipart-Streaming-Parser.
- Externer Distributed Cache / Redis-Cluster.
