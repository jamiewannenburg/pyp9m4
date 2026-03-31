"""JSON-friendly conversion for dataclasses and nested values (tuples → lists, enums, paths)."""

from __future__ import annotations

import base64
import enum
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

__all__ = ["dataclass_to_json_dict", "jsonify_for_api"]


def jsonify_for_api(obj: Any) -> Any:
    """Map values to JSON-friendly primitives (recursive).

    - Tuples and lists → lists of converted elements
    - Dicts → dicts with converted values
    :class:`enum.Enum` → :attr:`~enum.Enum.value`
    :class:`pathlib.Path` → :func:`str`
    :class:`bytes` → base64 ASCII string
    Scalars ``None``, ``bool``, ``int``, ``float``, ``str`` pass through unchanged.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if isinstance(obj, tuple):
        return [jsonify_for_api(x) for x in obj]
    if isinstance(obj, list):
        return [jsonify_for_api(x) for x in obj]
    if isinstance(obj, dict):
        return {k: jsonify_for_api(v) for k, v in obj.items()}
    return obj


def dataclass_to_json_dict(instance: Any) -> dict[str, Any]:
    """Convert a dataclass instance to a JSON-friendly ``dict`` (same rules as :func:`jsonify_for_api`)."""
    if not is_dataclass(instance):
        raise TypeError("expected a dataclass instance")
    raw = asdict(instance)
    return jsonify_for_api(raw)  # type: ignore[return-value]
