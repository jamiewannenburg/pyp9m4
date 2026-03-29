"""SMT-LIB 2 text helpers at the format boundary (stdlib only).

Optional integration with PySMT lives in :mod:`pyp9m4.bridge.pysmt_extra` and requires
the ``smt`` extra (``pip install pyp9m4[smt]``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_SET_LOGIC = re.compile(
    r"\(\s*set-logic\s+([^()\s]+)\s*\)",
    re.IGNORECASE,
)


def read_smtlib_text(path: Path | str, *, encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read an SMT-LIB script file as a single string."""
    return Path(path).read_text(encoding=encoding, errors=errors)


def write_smtlib_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = "\n",
) -> None:
    Path(path).write_text(text, encoding=encoding, newline=newline)


def extract_set_logic(script: str) -> str | None:
    """Return the first ``set-logic`` symbol, or ``None``."""
    m = _SET_LOGIC.search(script)
    return m.group(1) if m else None


def _skip_ws(i: int, s: str, n: int) -> int:
    while i < n and s[i] in " \t\r\n\v\f":
        i += 1
    return i


def _skip_line_comment(i: int, s: str, n: int) -> int:
    if i + 1 < n and s[i] == ";" and s[i + 1] != "|":
        while i < n and s[i] != "\n":
            i += 1
    return i


def _skip_bang_comment(i: int, s: str, n: int) -> int:
    if i + 1 < n and s[i] == "|" and s[i + 1] == "#":
        i += 2
        depth = 1
        while i < n and depth:
            if i + 1 < n and s[i] == "|" and s[i + 1] == "#":
                depth -= 1
                i += 2
            elif i + 1 < n and s[i] == "#" and s[i + 1] == "|":
                depth += 1
                i += 2
            else:
                i += 1
    return i


def _read_string_double(i: int, s: str, n: int) -> int:
    if i >= n or s[i] != '"':
        return i
    i += 1
    while i < n:
        if s[i] == '"':
            if i + 1 < n and s[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _read_symbol_bar(i: int, s: str, n: int) -> int:
    if i >= n or s[i] != "|":
        return i
    i += 1
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if s[i] == "|":
            return i + 1
        i += 1
    return i


def _scan_sexp(i: int, s: str, n: int) -> int:
    """Parse one S-expression starting at ``s[i]`` (must be ``'('``)."""
    if i >= n or s[i] != "(":
        raise ValueError("expected '('")
    depth = 0
    while i < n:
        i = _skip_ws(i, s, n)
        if i >= n:
            break
        c = s[i]
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            i += 1
            if depth == 0:
                return i
            continue
        if c == ";":
            i = _skip_line_comment(i, s, n)
            continue
        if c == "|" and i + 1 < n and s[i + 1] == "#":
            i = _skip_bang_comment(i, s, n)
            continue
        if c == '"':
            i = _read_string_double(i, s, n)
            continue
        if c == "|":
            i = _read_symbol_bar(i, s, n)
            continue
        i += 1
    raise ValueError("unbalanced parentheses in SMT-LIB script")


def iter_smtlib_commands(script: str) -> Iterator[str]:
    """Yield top-level parenthesized commands (comments skipped between forms)."""
    i = 0
    n = len(script)
    while True:
        i = _skip_ws(i, script, n)
        if i >= n:
            break
        if script[i] == ";":
            i = _skip_line_comment(i, script, n)
            continue
        if i + 1 < n and script[i] == "|" and script[i + 1] == "#":
            i = _skip_bang_comment(i, script, n)
            continue
        if script[i] != "(":
            raise ValueError(f"expected '(' at offset {i}")
        start = i
        i = _scan_sexp(i, script, n)
        yield script[start:i].strip()


@dataclass(frozen=True, slots=True)
class SmtlibCommandSummary:
    """First token inside the outer S-expression, when extractable."""

    head: str
    raw: str


def summarize_commands(commands: list[str]) -> list[SmtlibCommandSummary]:
    """Best-effort head symbol for each command string (for logging / tests)."""
    out: list[SmtlibCommandSummary] = []
    for raw in commands:
        inner = raw.strip()
        if not inner.startswith("(") or not inner.endswith(")"):
            out.append(SmtlibCommandSummary(head="?", raw=raw))
            continue
        body = inner[1:-1].strip()
        j = 0
        m = len(body)
        j = _skip_ws(j, body, m)
        if j >= m:
            out.append(SmtlibCommandSummary(head="?", raw=raw))
            continue
        if body[j] == "(":
            out.append(SmtlibCommandSummary(head="nested", raw=raw))
            continue
        if body[j] == "|":
            end = _read_symbol_bar(j, body, m)
            head = body[j:end]
        elif body[j] == '"':
            end = _read_string_double(j, body, m)
            head = body[j:end]
        else:
            k = j
            while k < m and body[k] not in " \t\r\n\v\f":
                k += 1
            head = body[j:k]
        out.append(SmtlibCommandSummary(head=head, raw=raw))
    return out
