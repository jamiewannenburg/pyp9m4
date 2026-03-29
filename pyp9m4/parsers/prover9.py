"""Parse Prover9 stdout / log text: section boundaries, statistics, proof bodies."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyp9m4.parsers.common import ParseWarning, match_section_title_line, parse_equals_key_values, split_ladr_section_blocks


@dataclass(frozen=True, slots=True)
class ProofSegment:
    """One ``PROOF`` … ``end of proof`` region (raw text, no inference-step AST)."""

    index: int | None
    text: str
    """Body inside the proof section (excluding outer delimiter lines)."""


@dataclass(frozen=True, slots=True)
class Prover9Parsed:
    """Result of :func:`parse_prover9_output`."""

    sections: dict[str, str]
    """Section title (delimiter inner title) -> body text until the next delimiter line."""

    statistics: dict[str, str]
    """Key/value pairs from the ``STATISTICS`` section, if present."""

    proof_segments: tuple[ProofSegment, ...]
    """Extracted proof bodies in order of appearance."""

    exit_phrases: tuple[str, ...]
    """Trailing non-section lines (e.g. ``THEOREM PROVED``, ``Exiting with …``)."""

    warnings: tuple[ParseWarning, ...] = ()


_PROOF_HDR_RE = re.compile(r"^%\s*Proof\s+(\d+)\s+", re.MULTILINE)


def parse_prover9_output(text: str) -> Prover9Parsed:
    """Parse Prover9 text: sections, statistics key-values, and proof segments.

    Does not build a clause-level proof DAG; proof bodies are opaque strings suitable
    for tools like ``prooftrans`` or manual inspection.
    """
    sections, sec_warnings = split_ladr_section_blocks(text)
    stats: dict[str, str] = {}
    if "STATISTICS" in sections:
        stats = parse_equals_key_values(sections["STATISTICS"])

    proof_segments: list[ProofSegment] = []
    if "PROOF" in sections:
        body = sections["PROOF"].strip("\n")
        m = _PROOF_HDR_RE.search(body)
        idx = int(m.group(1)) if m else None
        proof_segments.append(ProofSegment(index=idx, text=body))

    exit_phrases = _tail_after_last_delimiter(text)

    return Prover9Parsed(
        sections=sections,
        statistics=stats,
        proof_segments=tuple(proof_segments),
        exit_phrases=exit_phrases,
        warnings=tuple(sec_warnings),
    )


def _tail_after_last_delimiter(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    last_i = -1
    for i, line in enumerate(lines):
        if match_section_title_line(line) is not None:
            last_i = i
    if last_i < 0:
        return tuple(x.strip() for x in lines if x.strip())
    tail = lines[last_i + 1 :]
    return tuple(line.strip() for line in tail if line.strip())
