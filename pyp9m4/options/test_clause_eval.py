"""CLI fragments for ``test_clause_eval``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TestClauseEvalCliOptions:
    """Pass-through argv after the executable; consult ``test_clause_eval -h`` for your LADR build."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
