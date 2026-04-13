"""Read stdin or theory payloads from paths and file-like objects."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, TextIO

StdinSource = str | Path | BinaryIO | TextIO


def coerce_stdin_from_source(
    source: StdinSource,
    *,
    encoding: str,
    errors: str,
) -> str | bytes:
    """Load full content for :class:`~pyp9m4.runner.SubprocessInvocation` ``stdin``."""
    if isinstance(source, Path):
        return source.read_bytes()
    if isinstance(source, str):
        return Path(source).read_bytes()
    if isinstance(source, io.TextIOBase):
        return source.read()
    data = source.read()
    if not isinstance(data, bytes):
        raise TypeError(f"binary stream must read bytes, got {type(data).__name__}")
    return data


def read_theory_text(
    source: StdinSource,
    *,
    encoding: str,
    errors: str,
) -> str:
    """Load full problem text for :class:`~pyp9m4.theory.Theory`."""
    if isinstance(source, Path):
        return source.read_text(encoding=encoding, errors=errors)
    if isinstance(source, str):
        return Path(source).read_text(encoding=encoding, errors=errors)
    if isinstance(source, io.TextIOBase):
        return source.read()
    data = source.read()
    if not isinstance(data, bytes):
        raise TypeError(f"binary stream must read bytes, got {type(data).__name__}")
    return data.decode(encoding, errors=errors)


def iter_lines_for_interpretation_parse(
    source: StdinSource,
    *,
    encoding: str,
    errors: str,
) -> Iterator[str]:
    """Yield text lines (each ends with ``\\n`` when the underlying stream provides it)."""
    if isinstance(source, Path):
        with source.open(encoding=encoding, errors=errors, newline="") as f:
            yield from f
        return
    if isinstance(source, str):
        with open(source, encoding=encoding, errors=errors, newline="") as f:
            yield from f
        return
    if isinstance(source, io.TextIOBase):
        yield from source
        return
    while True:
        bline = source.readline()
        if not bline:
            break
        yield bline.decode(encoding, errors=errors)
