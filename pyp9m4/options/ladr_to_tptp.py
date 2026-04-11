"""CLI fragments for ``ladr_to_tptp``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LadrToTptpCliOptions:
    """Optional argv after the executable (stdin carries LADR input)."""

    quiet: bool = False
    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        out: list[str] = []
        if self.quiet:
            out.append("-q")
        out.extend(self.extra_argv)
        return out
