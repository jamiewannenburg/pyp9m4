"""Shared job / status types for high-level tool facades (async polling, web APIs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

JobLifecycle = Literal["pending", "running", "succeeded", "failed", "timed_out", "cancelled"]


@dataclass(frozen=True, slots=True)
class Mace4JobStatusSnapshot:
    """JSON-friendly snapshot from :meth:`~pyp9m4.mace4_facade.Mace4SearchHandle.status`.

    Progress fields are best-effort (parsed from Mace4 output and options), not full solver state.
    """

    lifecycle: JobLifecycle
    models_found: int
    last_domain_size: int | None
    current_size_range: tuple[int | None, int | None] | None
    """``(domain_size, end_size)`` from effective CLI options when a sweep is explicit; else ``None``."""

    exit_code: int | None
    stderr_tail: str
    argv: tuple[str, ...] = ()
    """Mace4 argv for the current or last run (debugging)."""
