"""Semantic I/O kinds for LADR tool chains (stdin/stdout roles, pipe compatibility).

These names follow the Prover9 / Mace4 manual: theory files, formula streams,
interpretation streams, proof logs, translator I/O, etc.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class IOKind(str, Enum):
    """What kind of data a stage consumes or produces in the fluent pipe model."""

    THEORY = "theory"
    """Full Prover9/Mace4 problem text (``formulas(...)`` / ``end_of_list.``, ``set``/``assign``, …)."""

    FORMULAS = "formulas"
    """Bare formulas or clauses (LADR syntax), not wrapped in ``formulas(..) end_of_list``."""

    INTERPRETATIONS = "interpretations"
    """Textual stream of ``interpretation(...)`` terms (Mace4, isofilter, interpformat, …)."""

    PROOFS = "proofs"
    """Prover9 log or prooftrans output."""

    TERMS = "terms"
    """Stream of LADR terms (e.g. rewriter stdin)."""

    DEMODULATORS = "demodulators"
    """Demodulator list read from a file (rewriter side input)."""

    TPTP_TEXT = "tptp_text"
    """TPTP-format text (e.g. ``tptp_to_ladr`` stdin)."""

    LADR_BARE_INPUT = "ladr_bare_input"
    """Bare LADR input from translators (stdout of ``tptp_to_ladr``, stdin style for Prover9/Mace4)."""

    INTERPRETATIONS_FILE = "interpretations_file"
    """Path to a file containing a *set* of interpretations (side input for clausefilter, clausetester, …)."""

    CLAUSETESTER_REPORT = "clausetester_report"
    """Plain-text report from ``clausetester`` (treat as :class:`str` at the value level)."""

    LADR_TEXT = "ladr_text"
    """Generic LADR-shaped text (e.g. ``renamer`` output) until a tool-specific kind is pinned."""


@runtime_checkable
class HasTheoryText(Protocol):
    """Object that can be rendered as full theory/problem text for prover9/mace4 stdin."""

    def to_theory_text(self) -> str:
        ...


@runtime_checkable
class HasLadrStdinText(Protocol):
    """Object that serializes to the bytes/text fed to a tool stdin."""

    def to_ladr_stdin_text(self) -> str:
        ...


@runtime_checkable
class HasInterpretationsFile(Protocol):
    """Side input: path to an interpretations file."""

    @property
    def interpretations_path(self) -> Path:
        ...
