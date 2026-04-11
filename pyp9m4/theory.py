"""Build canonical Prover9/Mace4 theory (problem) text from assumptions and goals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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

    def to_stage(
        self,
        *,
        cwd: Any = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        resolver: Any = None,
    ) -> Any:
        """Start a :class:`~pyp9m4.pipe.Stage` with theory text as stdin of the first tool."""
        from pyp9m4.io_kinds import IOKind
        from pyp9m4.pipe import Stage

        return Stage.source(
            self.to_theory_text(),
            kind=IOKind.THEORY,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
            resolver=resolver,
        )

    def mace4(self, *, cwd=None, env=None, timeout_s=None, resolver=None, **kwargs: Any) -> Any:
        """``Theory → mace4 → …``; see :meth:`~pyp9m4.pipe.Stage.mace4`."""
        return self.to_stage(cwd=cwd, env=env, timeout_s=timeout_s, resolver=resolver).mace4(**kwargs)

    def prover9(self, *, cwd=None, env=None, timeout_s=None, resolver=None, **kwargs: Any) -> Any:
        """``Theory → prover9 → …``; see :meth:`~pyp9m4.pipe.Stage.prover9`."""
        return self.to_stage(cwd=cwd, env=env, timeout_s=timeout_s, resolver=resolver).prover9(**kwargs)

    def fof_prover9(self, *, cwd=None, env=None, timeout_s=None, resolver=None, **kwargs: Any) -> Any:
        """``Theory → fof-prover9 → …``; see :meth:`~pyp9m4.pipe.Stage.fof_prover9`."""
        return self.to_stage(cwd=cwd, env=env, timeout_s=timeout_s, resolver=resolver).fof_prover9(**kwargs)

    def ladr_to_tptp(self, *, cwd=None, env=None, timeout_s=None, resolver=None, **kwargs: Any) -> Any:
        """``Theory → ladr_to_tptp → …``; see :meth:`~pyp9m4.pipe.Stage.ladr_to_tptp`."""
        return self.to_stage(cwd=cwd, env=env, timeout_s=timeout_s, resolver=resolver).ladr_to_tptp(**kwargs)
