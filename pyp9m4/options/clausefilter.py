"""CLI fragments for ``clausefilter`` (beyond required interpretations file + test name)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClausefilterCliOptions:
    """Optional argv placed *before* the interpretations file and test name."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
