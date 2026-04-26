from __future__ import annotations

import dataclasses
import functools
import inspect
import types
from typing import Any, Callable, get_args, get_origin, get_type_hints, Union

from .errors import HTTPError
from .request import Request

_NONE_TYPE = type(None)

class ValidationError(ValueError):
    pass

def _is_dataclass_type(tp: Any) -> bool:
    return inspect.isclass(tp) and dataclasses.is_dataclass(tp)

def _coerce_scalar(value: Any, tp: Any, name: str) -> Any:
    if tp is Any or tp is inspect.Signature.empty:
        return value
    if tp is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        raise ValidationError(f"{name}: expected bool")
    if tp is int:
        if isinstance(value, bool):
            raise ValidationError(f"{name}: expected int")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{name}: expected int") from exc
    if tp is float:
        if isinstance(value, bool):
            raise ValidationError(f"{name}: expected float")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{name}: expected float") from exc
    if tp is str:
        if isinstance(value, str):
            return value
        return str(value)
    if tp is bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        raise ValidationError(f"{name}: expected bytes")
    if inspect.isclass(tp):
        if isinstance(value, tp):
            return value
        raise ValidationError(f"{name}: expected {tp.__name__}")
    return value

def coerce_value(value: Any, tp: Any, name: str = "value") -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin in (Union, types.UnionType):
        errors: list[str] = []
        if _NONE_TYPE in args and value is None:
            return None
        for sub in args:
            if sub is _NONE_TYPE:
                continue
            try:
                return coerce_value(value, sub, name)
            except ValidationError as exc:
                errors.append(str(exc))
        raise ValidationError(f"{name}: does not match any allowed type ({'; '.join(errors)})")

    if origin in (list, tuple, set, frozenset):
        if not isinstance(value, (list, tuple, set, frozenset)):
            value = [value]
        item_type = args[0] if args else Any
        items = [coerce_value(v, item_type, f"{name}[]") for v in value]
        if origin is tuple:
            return tuple(items)
        if origin is set:
            return set(items)
        if origin is frozenset:
            return frozenset(items)
        return items

    if origin is dict:
        if not isinstance(value, dict):
            raise ValidationError(f"{name}: expected object")
        key_type, val_type = args if len(args) == 2 else (Any, Any)
        return {coerce_value(k, key_type, f"{name}.key"): coerce_value(v, val_type, f"{name}.{k}") for k, v in value.items()}

    if _is_dataclass_type(tp):
        if not isinstance(value, dict):
            raise ValidationError(f"{name}: expected object")
        return validate_model(tp, value)

    return _coerce_scalar(value, tp, name)

def validate_model(model_cls: type, data: dict[str, Any]) -> Any:
    if not dataclasses.is_dataclass(model_cls):
        raise TypeError("validation model must be a dataclass")
    hints = get_type_hints(model_cls)
    kwargs: dict[str, Any] = {}
    allowed = {field.name for field in dataclasses.fields(model_cls)}
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError("unknown field(s): " + ", ".join(sorted(unknown)))
    for field in dataclasses.fields(model_cls):
        tp = hints.get(field.name, Any)
        if field.name in data:
            kwargs[field.name] = coerce_value(data[field.name], tp, field.name)
            continue
        if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
            continue
        raise ValidationError(f"{field.name}: field required")
    return model_cls(**kwargs)

def validate_body(model_cls: type, *, attach_as: str = "validated_data") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "__sovereign_body_model__", model_cls)
        @functools.wraps(func)
        def wrapper(req: Request, *args: Any, **kwargs: Any) -> Any:
            try:
                data = req.json()
                if not isinstance(data, dict):
                    raise ValidationError("JSON body must be an object")
                setattr(req, attach_as, validate_model(model_cls, data))
            except HTTPError:
                raise
            except Exception as exc:
                raise HTTPError(400, f"Validation failed: {exc}") from exc
            return func(req, *args, **kwargs)
        setattr(wrapper, "__sovereign_body_model__", model_cls)
        return wrapper
    return decorator

def validate_query(model_cls: type, *, attach_as: str = "validated_query") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "__sovereign_query_model__", model_cls)
        @functools.wraps(func)
        def wrapper(req: Request, *args: Any, **kwargs: Any) -> Any:
            try:
                setattr(req, attach_as, validate_model(model_cls, dict(req.query)))
            except Exception as exc:
                raise HTTPError(400, f"Query validation failed: {exc}") from exc
            return func(req, *args, **kwargs)
        setattr(wrapper, "__sovereign_query_model__", model_cls)
        return wrapper
    return decorator

def schema_for_type(tp: Any) -> dict[str, Any]:
    origin = get_origin(tp)
    args = get_args(tp)
    if tp in (Any, inspect.Signature.empty):
        return {}
    if origin in (Union, types.UnionType):
        schemas = [schema_for_type(a) for a in args if a is not _NONE_TYPE]
        out = {"anyOf": schemas} if len(schemas) > 1 else (schemas[0] if schemas else {})
        if _NONE_TYPE in args:
            out = dict(out)
            out["nullable"] = True
        return out
    if origin in (list, tuple, set, frozenset):
        return {"type": "array", "items": schema_for_type(args[0] if args else Any)}
    if origin is dict:
        return {"type": "object", "additionalProperties": schema_for_type(args[1] if len(args) == 2 else Any)}
    if _is_dataclass_type(tp):
        return schema_for_dataclass(tp)
    mapping = {str: "string", int: "integer", float: "number", bool: "boolean", bytes: "string"}
    return {"type": mapping.get(tp, "string")}

def schema_for_dataclass(model_cls: type) -> dict[str, Any]:
    hints = get_type_hints(model_cls)
    props: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(model_cls):
        props[field.name] = schema_for_type(hints.get(field.name, Any))
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:  # type: ignore[attr-defined]
            required.append(field.name)
    out: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = required
    return out
