"""Tests for :mod:`pyp9m4.job_manager`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from pyp9m4.job_manager import JobManager, JobManagerError, JobMetadata, ManagedJobSnapshot
from pyp9m4.jobs import Prover9JobStatusSnapshot


class _FakeHandle:
    def __init__(self) -> None:
        self._life = "running"
        self._cancelled = False

    async def status(self) -> Prover9JobStatusSnapshot:
        return Prover9JobStatusSnapshot(
            lifecycle=self._life,  # type: ignore[arg-type]
            exit_code=None,
            stderr_tail="",
            argv=("prover9",),
        )

    def cancel(self) -> None:
        self._cancelled = True
        self._life = "cancelled"


@pytest.mark.asyncio
async def test_register_status_cancel() -> None:
    jm = JobManager()
    h = _FakeHandle()
    jid = jm.register(h, program="prover9")
    meta = jm.get(jid)
    assert isinstance(meta, JobMetadata)
    assert meta.program == "prover9"
    assert meta.job_id == jid

    s = await jm.status(jid)
    assert isinstance(s, ManagedJobSnapshot)
    assert s.lifecycle == "running"
    assert s.done is False
    assert s.snapshot is not None
    assert s.snapshot["lifecycle"] == "running"

    assert jm.cancel(jid) is True
    assert h._cancelled is True


@pytest.mark.asyncio
async def test_start_coroutine_success() -> None:
    jm = JobManager()

    async def work() -> str:
        await asyncio.sleep(0)
        return "ok"

    jid = jm.start(work, program="custom")
    # running or done depending on scheduling
    for _ in range(50):
        s = await jm.status(jid)
        if s.done:
            break
        await asyncio.sleep(0.01)
    s = await jm.status(jid)
    assert s.done is True
    assert s.lifecycle == "succeeded"
    assert s.result == "ok"


@pytest.mark.asyncio
async def test_start_coroutine_failure() -> None:
    jm = JobManager()

    async def boom() -> None:
        raise ValueError("x")

    jid = jm.start(boom)
    await asyncio.sleep(0.05)
    s = await jm.status(jid)
    assert s.done is True
    assert s.lifecycle == "failed"
    assert "ValueError" in (s.error or "")


@pytest.mark.asyncio
async def test_status_unknown_raises() -> None:
    jm = JobManager()
    with pytest.raises(JobManagerError):
        await jm.status(uuid4())


@pytest.mark.asyncio
async def test_ttl_evicts_after_terminal() -> None:
    jm = JobManager(ttl_s=0.05)

    async def work() -> int:
        await asyncio.sleep(0.01)
        return 1

    jid = jm.start(work)
    await asyncio.sleep(0.2)
    assert jm.get(jid) is None


@pytest.mark.asyncio
async def test_persist_path_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "jobs.jsonl"
    jm = JobManager(persist_path=path)

    async def work() -> str:
        return "y"

    jid = jm.start(work, program="p")
    await asyncio.sleep(0.05)
    text = path.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.strip().splitlines()]
    events = [x["event"] for x in lines]
    assert "start" in events
    assert "terminal" in events
    assert any(x.get("lifecycle") == "succeeded" for x in lines if x["event"] == "terminal")


@pytest.mark.asyncio
async def test_list_jobs_filter_program() -> None:
    jm = JobManager()
    h = _FakeHandle()
    jm.register(h, program="prover9")
    jm.register(_FakeHandle(), program="mace4")
    ids = jm.list_jobs(program="prover9")
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_close_cancels_cleanup_task() -> None:
    jm = JobManager(ttl_s=60.0)
    jm.register(_FakeHandle())
    assert jm._cleanup_task is not None
    await jm.close()
    assert jm._cleanup_task is None
