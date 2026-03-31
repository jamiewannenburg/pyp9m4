"""Loose ingestion of nested or GUI-wrapped option dicts (e.g. HTTP request bodies)."""

from __future__ import annotations

from dataclasses import MISSING, fields
from types import UnionType
from typing import Any, Literal, Mapping, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")

# Keys treated as one-level wrappers (e.g. ``{"value": 10}`` → ``10``).
_WRAPPER_KEYS: frozenset[str] = frozenset({"value", "default"})


def unwrap_gui_value(v: Any) -> Any:
    """If ``v`` looks like a single-key GUI wrapper, return the inner value (recursively).

    Recognizes dicts whose only key is ``value`` or ``default``. Nested wrappers are
    unwrapped in order until a non-wrapper dict, list, or scalar remains.
    """
    current: Any = v
    while isinstance(current, dict):
        keys = list(current.keys())
        if len(keys) != 1:
            break
        k = keys[0]
        if k not in _WRAPPER_KEYS:
            break
        current = current[k]
    return current


def coerce_mapping(
    flat: Mapping[str, Any],
    field_names: frozenset[str],
    *,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Keep only keys that belong to a dataclass field set, optionally remapping aliases.

    Unknown keys are dropped. If ``aliases`` maps ``alt`` → ``canonical``, only
    canonical names appear in the result.
    """
    out: dict[str, Any] = {}
    alias_map = aliases or {}
    for raw_key, val in flat.items():
        canonical = alias_map.get(raw_key, raw_key)
        if canonical in field_names:
            out[canonical] = val
    return out


def _union_args(tp: Any) -> tuple[Any, ...]:
    origin = get_origin(tp)
    if origin is Union:
        return get_args(tp)
    if origin is UnionType:
        return get_args(tp)
    return ()


def _is_optional(tp: Any) -> bool:
    return type(None) in _union_args(tp)


def _non_none_union_args(tp: Any) -> tuple[Any, ...]:
    return tuple(a for a in _union_args(tp) if a is not type(None))


def _coerce_literal(field_name: str, allowed: tuple[Any, ...], value: Any) -> Any:
    if value in allowed:
        return value
    if isinstance(value, str):
        for a in allowed:
            if isinstance(a, str) and a == value:
                return a
    raise ValueError(f"{field_name!r}: must be one of {allowed!r}, got {value!r}")


def _coerce_field(field_name: str, annotation: Any, value: Any) -> Any:
    value = unwrap_gui_value(value)
    if value is None and _is_optional(annotation):
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        return _coerce_literal(field_name, args, value)

    non_none = _non_none_union_args(annotation)
    if non_none:
        if len(non_none) == 1:
            return _coerce_field(field_name, non_none[0], value)
        for branch in non_none:
            try:
                return _coerce_field(field_name, branch, value)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"{field_name!r}: cannot coerce {value!r} to {annotation}")

    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"{field_name!r}: expected sequence, got {type(value).__name__}")
        elem_types = [a for a in args if a is not Ellipsis]
        if len(elem_types) == 1 and elem_types[0] is str:
            return tuple(str(x) for x in value)
        return tuple(value)

    if annotation is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes", "on"):
                return True
            if low in ("false", "0", "no", "off"):
                return False
        raise ValueError(f"{field_name!r}: expected bool, got {value!r}")

    if annotation is int:
        if isinstance(value, bool):
            raise ValueError(f"{field_name!r}: expected int, got bool")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip() != "":
            return int(value, 10)
        raise TypeError(f"{field_name!r}: expected int, got {type(value).__name__}")

    if annotation is str:
        if isinstance(value, str):
            return value
        return str(value)

    if isinstance(annotation, type) and isinstance(value, annotation):
        return value
    return value


def cli_options_from_nested_dict(
    cls: type[T],
    data: Mapping[str, Any] | None,
    *,
    strict: bool = False,
    warnings: list[str] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> T:
    """Build a frozen CLI options dataclass from a possibly nested / wrapped mapping.

    Unknown keys are ignored unless ``strict=True`` (then raises ``ValueError``).
    When ``warnings`` is a list, a message is appended for each unknown key.
    """
    if data is None:
        return cls()

    field_map = {f.name: f for f in fields(cls)}
    try:
        type_hints = get_type_hints(cls)
    except Exception:
        type_hints = {}
    field_names = frozenset(field_map.keys())
    alias_map = aliases or {}
    filtered = coerce_mapping(data, field_names, aliases=aliases)

    if strict:
        for raw_key in data:
            canonical = alias_map.get(raw_key, raw_key)
            if canonical not in field_names:
                raise ValueError(f"unknown option key: {raw_key!r}")

    if warnings is not None:
        for raw_key in data:
            canonical = alias_map.get(raw_key, raw_key)
            if canonical not in field_names:
                warnings.append(f"ignored unknown key: {raw_key!r}")

    kwargs: dict[str, Any] = {}
    for name, f in field_map.items():
        if name in filtered:
            try:
                anno = type_hints.get(name, f.type)
                kwargs[name] = _coerce_field(name, anno, filtered[name])
            except Exception as e:
                raise ValueError(f"invalid value for {name!r}: {e}") from e
        elif f.default is not MISSING:
            kwargs[name] = f.default
        elif f.default_factory is not MISSING:  # type: ignore[attr-defined]
            kwargs[name] = f.default_factory()  # type: ignore[misc]
        else:
            raise TypeError(f"{cls.__name__}.{name} has no default; cannot omit from mapping")

    return cls(**kwargs)
