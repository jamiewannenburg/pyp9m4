"""CLI fragments for ``renamer``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RenamerCliOptions:
    """Pass-through argv after the executable; consult ``renamer -h`` for your LADR build."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
