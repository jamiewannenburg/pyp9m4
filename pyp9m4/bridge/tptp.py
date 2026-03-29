"""TPTP file helpers and Prover9-oriented boundaries (stdlib only; no bundled parser deps).

Full TPTP is complex; :func:`iter_tptp_statements` handles common ``fof``/``cnf``/``tff``/``thf``/``include``
forms with line comments, block comments, and single-quoted strings. Exotic syntax may require
preprocessing or an optional third-party stack (see the ``tptp`` extra in ``pyproject.toml``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_TPTP_PROBLEM = re.compile(
    r"^\s*%\s*Problem\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TPTP_VERSION = re.compile(
    r"^\s*%\s*Version\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class TptpPreamble:
    """Metadata from leading ``%`` lines when present."""

    problem_name: str | None = None
    version: str | None = None


def read_tptp_text(path: Path | str, *, encoding: str = "utf-8", errors: str = "strict") -> str:
    """Read a TPTP problem file as a single Unicode string."""
    p = Path(path)
    return p.read_text(encoding=encoding, errors=errors)


def write_tptp_text(path: Path | str, text: str, *, encoding: str = "utf-8", newline: str | None = "\n") -> None:
    """Write text to *path* (creates parent directories is left to the caller)."""
    Path(path).write_text(text, encoding=encoding, newline=newline)


def parse_tptp_preamble(text: str) -> TptpPreamble:
    """Extract ``% Problem :`` / ``% Version :`` when they appear (best-effort)."""
    m = _TPTP_PROBLEM.search(text)
    v = _TPTP_VERSION.search(text)
    return TptpPreamble(
        problem_name=m.group(1).strip() if m else None,
        version=v.group(1).strip() if v else None,
    )


def iter_include_directives(text: str) -> Iterator[str]:
    """Yield path strings from ``include('...').`` / ``include("...").`` (best-effort)."""
    for m in re.finditer(
        r"\binclude\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\.",
        text,
        flags=re.DOTALL,
    ):
        yield m.group(1)


StatementKind = Literal["fof", "cnf", "tff", "thf", "include", "other"]


@dataclass(frozen=True, slots=True)
class TptpStatement:
    """One top-level TPTP statement (raw text slice, before any rewriting)."""

    kind: StatementKind
    name: str | None
    raw: str


def _skip_ws(i: int, s: str, n: int) -> int:
    while i < n and s[i] in " \t\r\n\v\f":
        i += 1
    return i


def _skip_line_comment(i: int, s: str, n: int) -> int:
    if i < n and s[i] == "%":
        while i < n and s[i] != "\n":
            i += 1
    return i


def _skip_block_comment(i: int, s: str, n: int) -> int:
    if i + 1 < n and s[i] == "/" and s[i + 1] == "*":
        i += 2
        while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
            i += 1
        if i + 1 < n:
            i += 2
    return i


def _skip_tptp_junk(i: int, s: str, n: int) -> int:
    while i < n:
        j = _skip_ws(i, s, n)
        if j > i:
            i = j
            continue
        k = _skip_line_comment(i, s, n)
        if k > i:
            i = k
            continue
        k = _skip_block_comment(i, s, n)
        if k > i:
            i = k
            continue
        break
    return i


def _read_quoted_string(i: int, s: str, n: int) -> int:
    """TPTP single-quoted strings; ``''`` is an escaped quote."""
    if i >= n or s[i] != "'":
        return i
    i += 1
    while i < n:
        if s[i] == "'":
            if i + 1 < n and s[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _scan_balanced_parens(i: int, s: str, n: int) -> int:
    """Assume ``s[i] == '('``. Return index after the matching ``)``."""
    depth = 0
    while i < n:
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
        if c == "'":
            i = _read_quoted_string(i, s, n)
            continue
        i += 1
    raise ValueError("unbalanced parentheses in TPTP text")


def iter_tptp_statements(text: str) -> Iterator[TptpStatement]:
    """Yield logical top-level statements; ends each unit at the required trailing ``.``."""
    i = 0
    n = len(text)
    while True:
        i = _skip_tptp_junk(i, text, n)
        if i >= n:
            break
        start = i
        j = i
        while j < n and (text[j].isalnum() or text[j] == "_"):
            j += 1
        if j == i:
            raise ValueError(f"unexpected character at offset {i}: {text[i : i + 20]!r}")
        ident = text[i:j].lower()
        i = _skip_ws(j, text, n)
        if i >= n or text[i] != "(":
            raise ValueError(f"expected '(' after {ident!r} at offset {start}")
        i = _scan_balanced_parens(i, text, n)
        i = _skip_ws(i, text, n)
        if i >= n or text[i] != ".":
            raise ValueError("expected '.' to end TPTP statement")
        i += 1
        raw = text[start:i]
        kind: StatementKind
        if ident in ("fof", "cnf", "tff", "thf"):
            kind = ident  # type: ignore[assignment]
        elif ident == "include":
            kind = "include"
        else:
            kind = "other"
        name = _statement_name(ident, text, j, n)
        yield TptpStatement(kind=kind, name=name, raw=raw.strip())


def _statement_name(ident: str, text: str, after_ident: int, n: int) -> str | None:
    if ident == "include":
        return None
    if ident not in ("fof", "cnf", "tff", "thf"):
        return None
    p0 = text.find("(", after_ident)
    if p0 < 0:
        return None
    p1 = _scan_balanced_parens(p0, text, n)
    inner = text[p0 + 1 : p1 - 1]
    comma = inner.find(",")
    if comma < 0:
        return None
    first = inner[:comma].strip()
    if len(first) >= 2 and first[0] == first[-1] and first[0] in "'\"":
        return first[1:-1]
    return first


def tptp_statements_as_prover9_comments(statements: list[TptpStatement]) -> str:
    """Render statements as ``%`` comments for side-by-side manual porting to Prover9 input."""
    lines: list[str] = [
        "% --- TPTP excerpt (not executable Prover9; translate to LADR syntax separately) ---",
    ]
    for st in statements:
        for line in st.raw.splitlines():
            lines.append("% " + line)
    return "\n".join(lines) + "\n"


def prover9_interop_note() -> str:
    """Short note on Prover9 vs TPTP for docstrings and logs."""
    return (
        "Prover9 uses LADR formulas (lists/terms), not TPTP syntax. "
        "Use this module for I/O and structure; translate semantics by hand or via external tools."
    )
