"""Parse Mace4 model output: ``interpretation(...)`` blocks and standard assignments."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from pyp9m4.parsers.common import ParseWarning, split_ladr_section_blocks


def _closing_paren_index(s: str, open_paren_idx: int) -> int:
    """Index of the ``)`` matching ``(`` at ``open_paren_idx`` (nested-aware)."""
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
    return len(s) - 1


def extract_interpretation_blocks(text: str) -> tuple[str, ...]:
    """Return each ``interpretation(...)`` substring (outermost parentheses)."""
    needle = "interpretation("
    out: list[str] = []
    pos = 0
    while True:
        i = text.find(needle, pos)
        if i < 0:
            break
        open_paren = i + len("interpretation")
        if open_paren >= len(text) or text[open_paren] != "(":
            pos = i + 1
            continue
        close = _closing_paren_index(text, open_paren)
        out.append(text[i : close + 1])
        pos = close + 1
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

    Portable format (whole file a nested list) is detected when the trimmed text starts with ``[``.
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
