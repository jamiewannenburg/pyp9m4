"""CLI fragments for ``tptp_to_ladr``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TptpToLadrCliOptions:
    """Optional argv after the executable (stdin carries TPTP text)."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
