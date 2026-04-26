class HTTPError(Exception):
    def __init__(self, status: int, message: str = "", headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message or STATUS_REASONS.get(status, "HTTP Error")
        self.headers = headers or {}

class ClientClosed(Exception):
    pass

class WebSocketClosed(Exception):
    pass

STATUS_REASONS = {
    101: "Switching Protocols", 200: "OK", 201: "Created", 204: "No Content",
    304: "Not Modified", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 408: "Request Timeout",
    411: "Length Required", 413: "Payload Too Large", 414: "URI Too Long",
    415: "Unsupported Media Type", 417: "Expectation Failed", 429: "Too Many Requests",
    431: "Request Header Fields Too Large", 500: "Internal Server Error",
    501: "Not Implemented", 503: "Service Unavailable", 505: "HTTP Version Not Supported",
}
