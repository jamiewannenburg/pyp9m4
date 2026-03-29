"""Shared job / status types for high-level tool facades (async polling, web APIs)."""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal, Protocol, runtime_checkable

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

    Suitable for JSON APIs (see :func:`job_status_snapshot_to_json_dict`). Call :meth:`!status`
    from the same :mod:`asyncio` event loop that started the job.
    """

    lifecycle: JobLifecycle
    exit_code: int | None
    stderr_tail: str
    argv: tuple[str, ...] = ()
    """Prover9 argv for the current or last run (debugging)."""
    duration_s: float | None = None
    """Wall time for the subprocess run, when the job has finished; else ``None``."""


@dataclass(frozen=True, slots=True)
class Mace4JobStatusSnapshot:
    """Immutable snapshot from :meth:`~pyp9m4.mace4_facade.Mace4SearchHandle.status`.

    Progress fields are best-effort (parsed from Mace4 output and CLI options), not full solver
    state. Call :meth:`!status` from the same :mod:`asyncio` event loop that started the job.
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


def _jsonify_for_api(obj: Any) -> Any:
    """Recursively map tuples to lists for JSON serialization."""
    if isinstance(obj, tuple):
        return [_jsonify_for_api(x) for x in obj]
    if isinstance(obj, list):
        return [_jsonify_for_api(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonify_for_api(v) for k, v in obj.items()}
    return obj


def job_status_snapshot_to_json_dict(
    snapshot: Prover9JobStatusSnapshot | Mace4JobStatusSnapshot,
) -> dict[str, Any]:
    """Convert a status snapshot to JSON-friendly primitives (lists instead of tuples)."""
    if not is_dataclass(snapshot):
        raise TypeError("expected a job status snapshot dataclass instance")
    raw = asdict(snapshot)
    return _jsonify_for_api(raw)  # type: ignore[return-value]


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
