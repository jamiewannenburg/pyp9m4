"""CLI fragments for ``interpfilter`` (beyond required file + test name)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterpfilterCliOptions:
    """Optional argv placed *before* the formulas file and test name (see ``interpfilter -h``)."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
