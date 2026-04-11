"""CLI fragments for ``clausetester`` (interpretations file is a separate keyword argument)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClausetesterCliOptions:
    """Optional argv placed *after* the interpretations file path."""

    extra_argv: tuple[str, ...] = ()

    def to_argv(self) -> list[str]:
        return list(self.extra_argv)
