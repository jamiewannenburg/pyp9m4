"""Parse Mace4 model output: ``interpretation(...)`` blocks and standard assignments."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from pyp9m4.parsers.common import ParseWarning, split_ladr_section_blocks


_INTERP_NEEDLE = "interpretation("
_LEN_INTERP_BEFORE_LPAREN = len("interpretation")


def _matching_close_paren(s: str, open_paren_idx: int) -> int | None:
    """Index of the ``)`` matching ``(`` at ``open_paren_idx``, or ``None`` if EOF leaves unclosed parens."""
    assert s[open_paren_idx] == "("
    depth = 0
    i = open_paren_idx
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _try_extract_next_interpretation(s: str, pos: int = 0) -> tuple[str, int] | None:
    """Next complete ``interpretation(...)`` starting at or after ``pos``, or ``None`` if none is complete yet."""
    while True:
        i = s.find(_INTERP_NEEDLE, pos)
        if i < 0:
            return None
        open_paren = i + _LEN_INTERP_BEFORE_LPAREN
        if open_paren >= len(s) or s[open_paren] != "(":
            pos = i + 1
            continue
        close = _matching_close_paren(s, open_paren)
        if close is None:
            return None
        return (s[i : close + 1], close + 1)


def extract_interpretation_blocks(text: str) -> tuple[str, ...]:
    """Return each complete ``interpretation(...)`` substring (outermost parentheses).

    Only balanced blocks are returned; a trailing incomplete ``interpretation(``… is ignored
    until closed (e.g. when using :class:`Mace4InterpretationBuffer` across chunks).
    """
    out: list[str] = []
    pos = 0
    while True:
        got = _try_extract_next_interpretation(text, pos)
        if got is None:
            break
        block, pos = got
        out.append(block)
    return tuple(out)


_DOMAIN_RE = re.compile(r"interpretation\s*\(\s*(\d+)\s*,")
_ASSIGN_LINE_RE = re.compile(
    r"^\s*(function|relation)\s*=\s*(.+?)\s*,?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StandardAssignment:
    """One line in Mace4 standard / standard2 structure output."""

    kind: str
    """``function`` or ``relation`` (lowercase)."""

    rhs: str
    """Right-hand side after ``=`` (trimmed)."""


@dataclass(frozen=True, slots=True)
class Mace4Interpretation:
    """One extracted model."""

    raw: str
    domain_size: int | None
    standard_assignments: tuple[StandardAssignment, ...]


@dataclass(frozen=True, slots=True)
class Mace4Parsed:
    """Result of :func:`parse_mace4_output`."""

    sections: dict[str, str]
    interpretations: tuple[Mace4Interpretation, ...]
    portable_lists: tuple[object, ...]
    """Top-level list objects from portable format (via :func:`ast.literal_eval`), if any."""

    warnings: tuple[ParseWarning, ...]


def _parse_standard_block(block: str) -> tuple[Mace4Interpretation, tuple[ParseWarning, ...]]:
    warnings: list[ParseWarning] = []
    dm = _DOMAIN_RE.search(block)
    domain = int(dm.group(1)) if dm else None
    assigns: list[StandardAssignment] = []
    for line in block.splitlines():
        line_st = line.strip()
        if not line_st or line_st.startswith("%"):
            continue
        m = _ASSIGN_LINE_RE.match(line_st)
        if m:
            assigns.append(StandardAssignment(kind=m.group(1).lower(), rhs=m.group(2).rstrip(",").strip()))
    if domain is None:
        warnings.append(ParseWarning("domain_size_not_found", "could not read interpretation(n,"))
    return (
        Mace4Interpretation(
            raw=block,
            domain_size=domain,
            standard_assignments=tuple(assigns),
        ),
        tuple(warnings),
    )


class Mace4InterpretationBuffer:
    """Buffer Mace4 stdout chunks and collect each complete ``interpretation(...)`` block.

    Call :meth:`feed` with successive fragments (e.g. from ``asyncio`` stream reads). Whenever
    a block's closing parenthesis arrives, the block is parsed with the same rules as
    :func:`parse_mace4_output`, so :class:`Mace4Interpretation` rows match batch parsing.

    **Portable format:** portable output is a single top-level ``[...]`` literal meant to be
    parsed with :func:`ast.literal_eval` on the **full** document. Incremental feeds cannot
    reliably detect or parse that form until EOF. For portable models, accumulate the full
    stdout string (or use :func:`parse_mace4_output` once at process exit). This buffer only
    extracts standard ``interpretation(...)`` structures incrementally.

    **Early break / cancel:** if you stop reading before the process ends, :attr:`buffered_tail`
    may hold an incomplete ``interpretation(``… fragment; discard the buffer or ignore it.
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[tuple[Mace4Interpretation, tuple[ParseWarning, ...]]]:
        """Append ``chunk`` and return newly completed interpretations (oldest first)."""
        if not chunk:
            return []
        self._buf += chunk
        out: list[tuple[Mace4Interpretation, tuple[ParseWarning, ...]]] = []
        pos = 0
        while True:
            got = _try_extract_next_interpretation(self._buf, pos)
            if got is None:
                break
            block, end = got
            mi, w = _parse_standard_block(block)
            out.append((mi, w))
            pos = end
        if pos > 0:
            self._buf = self._buf[pos:]
        return out

    def reset(self) -> None:
        """Clear the internal buffer."""
        self._buf = ""

    @property
    def buffered_tail(self) -> str:
        """Text not yet part of a complete ``interpretation(...)`` (preamble or incomplete tail)."""
        return self._buf


def _try_parse_portable(text: str) -> tuple[tuple[object, ...], tuple[ParseWarning, ...]]:
    """If ``text`` looks like a portable-format Python list, parse with :func:`ast.literal_eval`."""
    warnings: list[ParseWarning] = []
    stripped = text.strip()
    if not stripped.startswith("["):
        return (), ()
    try:
        obj = ast.literal_eval(stripped)
    except (SyntaxError, ValueError) as e:
        warnings.append(ParseWarning("portable_literal_eval_failed", str(e)))
        return (), tuple(warnings)
    if isinstance(obj, list):
        return (tuple(obj), tuple(warnings))
    return ((obj,), tuple(warnings))


def parse_mace4_output(text: str) -> Mace4Parsed:
    """Parse Mace4 text: LADR section blocks, ``interpretation`` structures, optional portable list.

    For **streaming** standard-structure output, use :class:`Mace4InterpretationBuffer` so each
    complete ``interpretation(...)`` is parsed as it arrives; that path reuses the same block
    parser as this function.

    **Portable format** (whole file a nested list) is detected when trimmed text starts with
    ``[``. It is evaluated only on the **entire** string passed here — not incrementally — so
    callers using portable mode should buffer full stdout (or pipe to a string) before
    calling. Standard ``interpretation(...)`` blocks in the same run are still extracted when
    present.

    Standard assignments are best-effort regex lines ``function = …`` / ``relation = …``.
    """
    sections, sec_warn = split_ladr_section_blocks(text)
    blocks = extract_interpretation_blocks(text)
    interp: list[Mace4Interpretation] = []
    all_warn: list[ParseWarning] = list(sec_warn)

    if not blocks and "interpretation(" in text.lower():
        all_warn.append(
            ParseWarning(
                "interpretation_unbalanced",
                "saw 'interpretation(' but could not match balanced parentheses",
            )
        )

    for b in blocks:
        mi, w = _parse_standard_block(b)
        interp.append(mi)
        all_warn.extend(w)

    portable: tuple[object, ...] = ()
    p_warn: tuple[ParseWarning, ...] = ()
    if not blocks:
        portable, p_warn = _try_parse_portable(text)
        all_warn.extend(p_warn)

    return Mace4Parsed(
        sections=sections,
        interpretations=tuple(interp),
        portable_lists=portable,
        warnings=tuple(all_warn),
    )
