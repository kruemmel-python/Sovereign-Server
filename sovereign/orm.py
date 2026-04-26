from __future__ import annotations

import dataclasses, json, sqlite3, threading, time
from pathlib import Path
from types import NoneType
from typing import Any, Generic, Iterable, TypeVar, get_args, get_origin, get_type_hints

T = TypeVar("T")


def _sqlite_type(tp: Any) -> str:
    origin = get_origin(tp)
    args = get_args(tp)
    if origin is None and tp is NoneType:
        return "TEXT"
    if origin is not None and NoneType in args:
        return _sqlite_type(next(a for a in args if a is not NoneType))
    if tp in (int, bool):
        return "INTEGER"
    if tp is float:
        return "REAL"
    if tp is bytes:
        return "BLOB"
    return "TEXT"


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return json.dumps(dataclasses.asdict(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _decode(value: Any, tp: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    args = get_args(tp)
    if origin is not None and NoneType in args:
        tp = next(a for a in args if a is not NoneType)
        origin = get_origin(tp)
    if tp is bool:
        return bool(value)
    if tp is int:
        return int(value)
    if tp is float:
        return float(value)
    if tp is bytes:
        return value
    if origin in (list, dict, tuple, set) or dataclasses.is_dataclass(tp):
        data = json.loads(value)
        if dataclasses.is_dataclass(tp):
            return tp(**data)
        if origin is tuple:
            return tuple(data)
        if origin is set:
            return set(data)
        return data
    return value


@dataclasses.dataclass
class Model:
    id: int | None = None

    @classmethod
    def table_name(cls) -> str:
        return getattr(cls, "__tablename__", cls.__name__.lower())

    @classmethod
    def primary_key(cls) -> str:
        return getattr(cls, "__primary_key__", "id")


class Query(Generic[T]):
    def __init__(self, db: "SQLiteORM", model: type[T]) -> None:
        self.db = db
        self.model = model
        self._where: dict[str, Any] = {}
        self._limit: int | None = None
        self._order: str | None = None

    def where(self, **kwargs: Any) -> "Query[T]":
        self._where.update(kwargs)
        return self

    def limit(self, n: int) -> "Query[T]":
        self._limit = int(n)
        return self

    def order_by(self, field: str, descending: bool = False) -> "Query[T]":
        if not field.replace("_", "").isalnum():
            raise ValueError("invalid order field")
        self._order = field + (" DESC" if descending else " ASC")
        return self

    def all(self) -> list[T]:
        return self.db._select(self.model, self._where, self._limit, self._order)

    def first(self) -> T | None:
        self._limit = 1
        rows = self.all()
        return rows[0] if rows else None


class SQLiteORM:
    """Tiny dataclass-first SQLite ORM with explicit parameter binding."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._init_pragmas()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_pragmas(self) -> None:
        with self.connect():
            pass

    def create_table(self, model: type[Any]) -> None:
        if not dataclasses.is_dataclass(model):
            raise TypeError("model must be a dataclass")
        hints = get_type_hints(model)
        fields = []
        pk = getattr(model, "primary_key", lambda: "id")()
        for f in dataclasses.fields(model):
            col_type = _sqlite_type(hints.get(f.name, Any))
            if f.name == pk:
                if col_type == "INTEGER":
                    fields.append(f"{f.name} INTEGER PRIMARY KEY AUTOINCREMENT")
                else:
                    fields.append(f"{f.name} {col_type} PRIMARY KEY")
            else:
                fields.append(f"{f.name} {col_type}")
        sql = f"CREATE TABLE IF NOT EXISTS {model.table_name()} ({', '.join(fields)})"
        with self.lock, self.connect() as con:
            con.execute(sql)

    def create_all(self, models: Iterable[type[Any]]) -> None:
        for model in models:
            self.create_table(model)

    def insert(self, obj: T) -> T:
        model = type(obj)
        self.create_table(model)
        pk = model.primary_key()
        values = dataclasses.asdict(obj)
        fields = [k for k, v in values.items() if not (k == pk and v is None)]
        params = [_encode(values[k]) for k in fields]
        placeholders = ",".join("?" for _ in fields)
        sql = f"INSERT INTO {model.table_name()} ({','.join(fields)}) VALUES ({placeholders})"
        with self.lock, self.connect() as con:
            cur = con.execute(sql, params)
            if pk in values and values.get(pk) is None:
                try:
                    setattr(obj, pk, int(cur.lastrowid))
                except Exception:
                    pass
        return obj

    def save(self, obj: T) -> T:
        model = type(obj)
        pk = model.primary_key()
        pk_value = getattr(obj, pk)
        if pk_value is None:
            return self.insert(obj)
        self.create_table(model)
        values = dataclasses.asdict(obj)
        fields = [k for k in values if k != pk]
        assignments = ",".join(f"{k}=?" for k in fields)
        params = [_encode(values[k]) for k in fields] + [pk_value]
        with self.lock, self.connect() as con:
            cur = con.execute(f"UPDATE {model.table_name()} SET {assignments} WHERE {pk}=?", params)
            if cur.rowcount == 0:
                self.insert(obj)
        return obj

    def delete(self, obj: Any) -> int:
        model = type(obj)
        pk = model.primary_key()
        with self.lock, self.connect() as con:
            cur = con.execute(f"DELETE FROM {model.table_name()} WHERE {pk}=?", (getattr(obj, pk),))
            return int(cur.rowcount)

    def query(self, model: type[T]) -> Query[T]:
        self.create_table(model)
        return Query(self, model)

    def get(self, model: type[T], pk_value: Any) -> T | None:
        pk = model.primary_key()
        return self.query(model).where(**{pk: pk_value}).first()

    def _select(self, model: type[T], where: dict[str, Any], limit: int | None, order: str | None) -> list[T]:
        hints = get_type_hints(model)
        sql = f"SELECT * FROM {model.table_name()}"
        params: list[Any] = []
        if where:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
            params.extend(_encode(v) for v in where.values())
        if order:
            sql += " ORDER BY " + order
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.lock, self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        out = []
        for row in rows:
            data = {k: _decode(row[k], hints.get(k, Any)) for k in row.keys()}
            out.append(model(**data))
        return out
