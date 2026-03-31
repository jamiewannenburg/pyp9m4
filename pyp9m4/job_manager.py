"""Central job registry: UUIDs, asyncio tasks, optional handles, snapshots, cancel, TTL, optional persistence."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pyp9m4.jobs import JobLifecycle
from pyp9m4.serialization import dataclass_to_json_dict, jsonify_for_api

__all__ = ["JobManager", "ManagedJobSnapshot", "JobMetadata", "JobManagerError"]


class JobManagerError(LookupError):
    """Raised when a job id is unknown or has been evicted."""


def _is_terminal_lifecycle(life: str | None) -> bool:
    if life is None:
        return False
    return life in ("succeeded", "failed", "timed_out", "cancelled")


@dataclass(slots=True)
class _JobRecord:
    job_id: UUID
    program: str | None
    created_at: float
    task: asyncio.Task[Any] | None
    handle: Any | None
    last_snapshot: dict[str, Any] | None
    result: Any | None = None
    error: BaseException | None = None
    expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class JobMetadata:
    """Lightweight sync lookup: ``job_id``, ``program``, ``created_at`` (no I/O)."""

    job_id: UUID
    program: str | None
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        d = dataclass_to_json_dict(self)
        d["job_id"] = str(self.job_id)
        return d


@dataclass(frozen=True, slots=True)
class ManagedJobSnapshot:
    """Point-in-time view of a managed job (``job_id``, ``program``, tool snapshot, terminal state)."""

    job_id: UUID
    program: str | None
    lifecycle: JobLifecycle | None
    created_at: float
    snapshot: dict[str, Any] | None
    result: Any | None
    error: str | None
    done: bool

    def to_dict(self) -> dict[str, Any]:
        d = dataclass_to_json_dict(self)
        d["job_id"] = str(self.job_id)
        if self.result is not None and hasattr(self.result, "to_dict"):
            d["result"] = self.result.to_dict()
        else:
            d["result"] = jsonify_for_api(self.result)
        return d


class JobManager:
    """In-memory registry of background jobs with optional TTL eviction and JSONL persistence.

    Use :meth:`register` for existing facade handles (:class:`~pyp9m4.prover9_facade.Prover9ProofHandle`,
    :class:`~pyp9m4.mace4_facade.Mace4SearchHandle`, etc.) or :meth:`start` for a coroutine factory.
    Call :meth:`status` from the same asyncio event loop that created the jobs.
    """

    def __init__(
        self,
        *,
        ttl_s: float | None = None,
        persist_path: Path | None = None,
    ) -> None:
        self._ttl_s = ttl_s
        self._persist_path = persist_path
        self._records: dict[UUID, _JobRecord] = {}
        self._mtx = threading.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    def _schedule_ttl_cleanup(self) -> None:
        if self._ttl_s is None or self._ttl_s <= 0:
            return
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return

        async def _loop() -> None:
            try:
                while True:
                    await asyncio.sleep(min(1.0, self._ttl_s / 2))
                    with self._mtx:
                        self._evict_expired_unlocked()
            except asyncio.CancelledError:
                return

        try:
            self._cleanup_task = asyncio.create_task(_loop())
        except RuntimeError:
            self._cleanup_task = None

    def _evict_expired_unlocked(self) -> None:
        now = time.monotonic()
        dead = [jid for jid, r in self._records.items() if r.expires_at is not None and now >= r.expires_at]
        for jid in dead:
            del self._records[jid]

    def _evict_expired(self) -> None:
        with self._mtx:
            self._evict_expired_unlocked()

    def _maybe_set_expiry(self, rec: _JobRecord, lifecycle: str | None) -> None:
        if self._ttl_s is None or self._ttl_s <= 0:
            return
        if _is_terminal_lifecycle(lifecycle):
            rec.expires_at = time.monotonic() + self._ttl_s

    def _persist(self, event: str, rec: _JobRecord, extra: Mapping[str, Any] | None = None) -> None:
        if self._persist_path is None:
            return
        payload: dict[str, Any] = {
            "event": event,
            "job_id": str(rec.job_id),
            "program": rec.program,
            "created_at": rec.created_at,
        }
        if extra:
            payload.update(extra)
        line = json.dumps(payload, default=str) + "\n"
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with self._persist_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def register(self, handle: Any, *, program: str | None = None) -> UUID:
        """Register an existing async handle (e.g. from ``Prover9.start_arun``). Returns a new job id."""
        job_id = uuid4()
        rec = _JobRecord(
            job_id=job_id,
            program=program,
            created_at=time.monotonic(),
            task=None,
            handle=handle,
            last_snapshot=None,
        )
        with self._mtx:
            self._records[job_id] = rec
        self._schedule_ttl_cleanup()
        self._persist("register", rec)
        return job_id

    def start(
        self,
        factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        program: str | None = None,
    ) -> UUID:
        """Schedule ``factory()`` as a task and return its job id."""

        job_id = uuid4()
        rec = _JobRecord(
            job_id=job_id,
            program=program,
            created_at=time.monotonic(),
            task=None,
            handle=None,
            last_snapshot=None,
        )

        async def _runner() -> None:
            try:
                rec.result = await factory()
            except asyncio.CancelledError as e:
                rec.error = e
                self._maybe_set_expiry(rec, "cancelled")
                self._persist("terminal", rec, {"lifecycle": "cancelled"})
                raise
            except BaseException as e:
                rec.error = e
                self._maybe_set_expiry(rec, "failed")
                self._persist("terminal", rec, {"lifecycle": "failed", "error": repr(e)})
                raise
            else:
                self._maybe_set_expiry(rec, "succeeded")
                self._persist("terminal", rec, {"lifecycle": "succeeded"})

        task = asyncio.create_task(_runner())
        rec.task = task
        with self._mtx:
            self._records[job_id] = rec
        self._schedule_ttl_cleanup()
        self._persist("start", rec)
        return job_id

    def get(self, job_id: UUID) -> JobMetadata | None:
        """Return stable metadata if the job is still registered, else ``None``."""
        self._evict_expired()
        with self._mtx:
            rec = self._records.get(job_id)
            if rec is None:
                return None
            return JobMetadata(job_id=rec.job_id, program=rec.program, created_at=rec.created_at)

    async def status(self, job_id: UUID) -> ManagedJobSnapshot:
        """Refresh status from the handle or task and return a :class:`ManagedJobSnapshot`."""
        self._evict_expired()
        with self._mtx:
            rec = self._records.get(job_id)
            if rec is None:
                raise JobManagerError(str(job_id))
            handle = rec.handle
            task = rec.task
            program = rec.program
            created_at = rec.created_at

        lifecycle: JobLifecycle | None = None
        snap_dict: dict[str, Any] | None = None
        err_s: str | None = None
        done = False

        if handle is not None and hasattr(handle, "status"):
            hs = await handle.status()
            snap_dict = hs.to_dict() if hasattr(hs, "to_dict") else {"value": repr(hs)}
            life_raw = snap_dict.get("lifecycle")
            lifecycle = life_raw if isinstance(life_raw, str) else None
            done = bool(lifecycle and _is_terminal_lifecycle(lifecycle))
            with self._mtx:
                r2 = self._records.get(job_id)
                if r2 is not None:
                    r2.last_snapshot = snap_dict
                    self._maybe_set_expiry(r2, lifecycle)
        elif task is not None:
            if not task.done():
                lifecycle = "running"
                done = False
                with self._mtx:
                    r2 = self._records.get(job_id)
                    snap_dict = r2.last_snapshot if r2 is not None else None
            else:
                done = True
                if task.cancelled():
                    lifecycle = "cancelled"
                    err_s = "cancelled"
                else:
                    exc = task.exception()
                    if exc is not None:
                        if isinstance(exc, asyncio.CancelledError):
                            lifecycle = "cancelled"
                            err_s = "cancelled"
                        else:
                            lifecycle = "failed"
                            err_s = repr(exc)
                            with self._mtx:
                                r2 = self._records.get(job_id)
                                if r2 is not None:
                                    r2.error = exc
                    else:
                        lifecycle = "succeeded"
                        tr = task.result()
                        with self._mtx:
                            r2 = self._records.get(job_id)
                            if r2 is not None and r2.result is None:
                                r2.result = tr
                snap_dict = None
                with self._mtx:
                    r2 = self._records.get(job_id)
                    if r2 is not None:
                        self._maybe_set_expiry(r2, lifecycle)
                        if snap_dict is None:
                            snap_dict = r2.last_snapshot
        else:
            done = True
            lifecycle = "failed"
            err_s = "invalid record"

        with self._mtx:
            r3 = self._records.get(job_id)
            if r3 is not None and snap_dict is not None:
                r3.last_snapshot = snap_dict
            if r3 is not None and r3.error is not None and err_s is None:
                err_s = repr(r3.error)
            final_snap = r3.last_snapshot if r3 is not None else snap_dict
            final_result = r3.result if r3 is not None else None

        return ManagedJobSnapshot(
            job_id=job_id,
            program=program,
            lifecycle=lifecycle,
            created_at=created_at,
            snapshot=final_snap,
            result=final_result,
            error=err_s,
            done=done,
        )

    def cancel(self, job_id: UUID) -> bool:
        """Cancel the underlying task or handle. Returns ``False`` if the job is unknown."""
        self._evict_expired()
        with self._mtx:
            rec = self._records.get(job_id)
            if rec is None:
                return False
            handle = rec.handle
            task = rec.task
        if handle is not None:
            cancel_fn = getattr(handle, "cancel", None)
            if callable(cancel_fn):
                cancel_fn()
        elif task is not None:
            task.cancel()
        return True

    def list_jobs(
        self,
        *,
        program: str | None = None,
        lifecycle: JobLifecycle | None = None,
    ) -> list[UUID]:
        """List job ids, optionally filtered by ``program`` (exact) or ``lifecycle`` (cached snapshot)."""
        self._evict_expired()
        with self._mtx:
            items = list(self._records.items())
        out: list[UUID] = []
        for jid, rec in items:
            if program is not None and rec.program != program:
                continue
            if lifecycle is not None:
                ls = (rec.last_snapshot or {}).get("lifecycle")
                if ls != lifecycle:
                    continue
            out.append(jid)
        return out

    async def close(self) -> None:
        """Stop the background TTL loop if it was started."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
