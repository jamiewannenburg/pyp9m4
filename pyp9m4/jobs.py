"""Shared job / status types for high-level tool facades (async polling, web APIs)."""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pyp9m4.serialization import dataclass_to_json_dict

if TYPE_CHECKING:
    from pyp9m4.parsers.mace4 import Mace4StdoutMetadata

JobLifecycle = Literal["pending", "running", "succeeded", "failed", "timed_out", "cancelled"]


class JobLifecyclePhase(str, enum.Enum):
    """Public lifecycle labels for jobs; values match :data:`JobLifecycle` strings (JSON-friendly)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


def is_job_lifecycle_string(value: str) -> bool:
    """Return True if ``value`` is a valid :data:`JobLifecycle` string."""
    return value in _JOB_LIFECYCLE_VALUES


_JOB_LIFECYCLE_VALUES: frozenset[str] = frozenset(m.value for m in JobLifecyclePhase)


@dataclass(frozen=True, slots=True)
class Prover9JobStatusSnapshot:
    """Immutable snapshot from :meth:`~pyp9m4.prover9_facade.Prover9ProofHandle.status`.

    Suitable for JSON APIs (see :meth:`to_dict` / :func:`job_status_snapshot_to_json_dict`). Call :meth:`!status`
    from the same :mod:`asyncio` event loop that started the job.
    """

    lifecycle: JobLifecycle
    exit_code: int | None
    stderr_tail: str
    argv: tuple[str, ...] = ()
    """Prover9 argv for the current or last run (debugging)."""
    duration_s: float | None = None
    """Wall time for the subprocess run, when the job has finished; else ``None``."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot (lists instead of tuples)."""
        return dataclass_to_json_dict(self)


@dataclass(frozen=True, slots=True)
class Mace4JobStatusSnapshot:
    """Immutable snapshot from :meth:`~pyp9m4.mace4_facade.Mace4SearchHandle.status`.

    Progress fields are best-effort (parsed from Mace4 output and CLI options), not full solver
    state. For JSON, use :meth:`to_dict` or :func:`job_status_snapshot_to_json_dict`. Call :meth:`!status`
    from the same :mod:`asyncio` event loop that started the job.
    """

    lifecycle: JobLifecycle
    models_found: int
    last_domain_size: int | None
    current_size_range: tuple[int | None, int | None] | None
    """``(domain_size, end_size)`` from effective CLI options when ``-n`` / ``-N`` are set; else ``None``."""

    exit_code: int | None
    stderr_tail: str
    argv: tuple[str, ...] = ()
    """Mace4 argv for the current or last run (debugging)."""
    domain_increment: int | None = None
    """``-i`` increment from effective options when a domain sweep may be explicit; else ``None``."""

    duration_s: float | None = None
    """Wall time for the search (pipeline included when isomorphic filtering is on), when finished."""

    mace4_metadata: "Mace4StdoutMetadata | None" = None
    """Parsed transcript (preamble, statistics, per-domain counts) when stdout was available at exit."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot (lists instead of tuples)."""
        return dataclass_to_json_dict(self)


def job_status_snapshot_to_json_dict(
    snapshot: Prover9JobStatusSnapshot | Mace4JobStatusSnapshot,
) -> dict[str, Any]:
    """Convert a status snapshot to JSON-friendly primitives (lists instead of tuples).

    Equivalent to :meth:`Prover9JobStatusSnapshot.to_dict` / :meth:`Mace4JobStatusSnapshot.to_dict`.
    """
    if not isinstance(snapshot, (Prover9JobStatusSnapshot, Mace4JobStatusSnapshot)):
        raise TypeError("expected a job status snapshot dataclass instance")
    return snapshot.to_dict()


@runtime_checkable
class Prover9AsyncJobHandle(Protocol):
    """Async handle for a background Prover9 run (see :class:`~pyp9m4.prover9_facade.Prover9ProofHandle`)."""

    async def status(self) -> Prover9JobStatusSnapshot:
        """Point-in-time lifecycle, stderr tail, exit code, and timing (best-effort)."""
        ...

    async def wait(self) -> None:
        ...

    async def result(self) -> Any:
        """Parsed proof result when the job succeeds; raises if unavailable."""
        ...

    def cancel(self) -> None:
        ...

    async def event_stream(self) -> AsyncIterator[dict[str, Any]]:
        """SSE-friendly line and lifecycle events (see concrete handle)."""
        ...


@runtime_checkable
class Mace4AsyncJobHandle(Protocol):
    """Async handle for a background Mace4 search (see :class:`~pyp9m4.mace4_facade.Mace4SearchHandle`)."""

    async def status(self) -> Mace4JobStatusSnapshot:
        """Lifecycle, errors, model count, and domain-sweep hints (best-effort)."""
        ...

    async def wait(self) -> None:
        ...

    async def result(self) -> None:
        ...

    def cancel(self) -> None:
        ...

    async def amodels(self) -> AsyncIterator[Any]:
        """Async iterator of models (see concrete handle)."""
        ...

    async def event_stream(self) -> AsyncIterator[dict[str, Any]]:
        """SSE-friendly line, model, and lifecycle events (see concrete handle)."""
        ...
