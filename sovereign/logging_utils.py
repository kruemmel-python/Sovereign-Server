from __future__ import annotations
import contextvars, json, logging, time, uuid

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

def new_request_id() -> str:
    return uuid.uuid4().hex

def set_request_id(value: str) -> None:
    request_id_var.set(value)

def get_request_id() -> str:
    return request_id_var.get("-")

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "process": record.process,
            "thread": record.threadName,
        }
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def configure_logging(json_logs: bool = False, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if json_logs:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(message)s"))
    root = logging.getLogger("sovereign")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
