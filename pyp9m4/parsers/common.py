"""Shared parsing utilities and warnings."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """Non-fatal parse issue (unexpected shape, partial extraction)."""

    message: str
    detail: str | None = None


# Lines like ``============================== PROOF =================================``
_SECTION_LINE_RE = re.compile(r"^={20,}\s*(?P<title>[^=\n]+?)\s*={10,}\s*$")


def match_section_title_line(line: str) -> str | None:
    """If ``line`` is a Prover9-style section delimiter, return the title; else ``None``."""
    m = _SECTION_LINE_RE.match(line.rstrip("\r\n"))
    if not m:
        return None
    return m.group("title").strip()


def split_ladr_section_blocks(text: str) -> tuple[dict[str, str], tuple[ParseWarning, ...]]:
    """Split output on ``============================== Title =====`` lines (Prover9 / Mace4 style)."""
    warnings: list[ParseWarning] = []
    lines = text.splitlines()
    sections: dict[str, str] = {}
    current_title: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current_title, buf
        if current_title is not None:
            body = "\n".join(buf)
            if current_title in sections:
                warnings.append(
                    ParseWarning(
                        "duplicate_section_title",
                        f"section {current_title!r} appeared more than once; last wins",
                    )
                )
            sections[current_title] = body
        current_title = None
        buf = []

    for line in lines:
        title = match_section_title_line(line)
        if title is not None:
            flush()
            current_title = title
        elif current_title is not None:
            buf.append(line)

    flush()
    return sections, tuple(warnings)


def parse_equals_key_values(blob: str) -> dict[str, str]:
    """Parse ``Key=value`` tokens from a blob where keys are identifiers (Prover9 statistics).

    Values run until the next ``Key=`` (case-sensitive) or end of string. Trailing ``.`` on
    values is stripped when it is not part of a decimal number.
    """
    key_re = re.compile(r"([A-Za-z_]\w*)\s*=\s*")
    matches = list(key_re.finditer(blob))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(blob)
        raw = blob[start:end].strip()
        raw = raw.rstrip(",")
        val = raw
        if val.endswith(".") and not re.search(r"\d\.\d\.$", val):
            val = val[:-1].strip()
        out[key] = val
    return out
