"""CLI fragments for ``rewriter`` (beyond required demodulators file)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RewriterCliOptions:
    """Optional argv placed *before* the demodulators file path."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
