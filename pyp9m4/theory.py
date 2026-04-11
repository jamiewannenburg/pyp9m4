"""Build canonical Prover9/Mace4 theory (problem) text from assumptions and goals."""

from __future__ import annotations

from collections.abc import Sequence

from pyp9m4.io_kinds import HasTheoryText


def _normalize_lines(spec: str | Sequence[str]) -> str:
    if isinstance(spec, str):
        return spec.strip("\n")
    parts = [s.rstrip() for s in spec]
    return "\n".join(parts).strip("\n")


def _section(list_name: str, body: str) -> str:
    inner = f"\n{body}\n" if body else "\n"
    return f"formulas({list_name}).{inner}end_of_list.\n"


class Theory(HasTheoryText):
    """Full LADR problem text for ``prover9`` / ``mace4`` (and similar) stdin.

    Either pass :paramref:`~Theory.text` as the complete problem, or build from
    :paramref:`~Theory.assumptions` and :paramref:`~Theory.goals` with optional
    :paramref:`~Theory.options` lines (``set``/``assign``/comments) before the lists.
    """

    __slots__ = ("_text",)

    def __init__(
        self,
        assumptions: str | Sequence[str] = (),
        goals: str | Sequence[str] = (),
        *,
        text: str | None = None,
        options: str | Sequence[str] | None = None,
    ) -> None:
        if text is not None:
            self._text = text
            return
        opt = _normalize_lines(options) if options is not None else ""
        opt_block = f"{opt}\n" if opt else ""
        a = _normalize_lines(assumptions)
        g = _normalize_lines(goals)
        self._text = f"{opt_block}{_section('assumptions', a)}{_section('goals', g)}"

    def to_theory_text(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        if len(self._text) > 72:
            return f"Theory({self._text[:36]!r}…{len(self._text)} chars…)"
        return f"Theory({self._text!r})"
