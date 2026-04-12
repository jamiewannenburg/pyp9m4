"""Tests for :mod:`pyp9m4.pipeline` fluent chain API."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyp9m4 import pipeline
from pyp9m4.pipeline import ChainResult, PipelineBuilder
from pyp9m4.runner import AsyncToolRunner, RunStatus, ToolRunResult


@pytest.mark.asyncio
async def test_pipeline_isofilter_interpformat_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_run(self: AsyncToolRunner, inv: object) -> ToolRunResult:
        argv = getattr(inv, "argv", ())
        stdin = getattr(inv, "stdin", None)
        stem = Path(argv[0]).stem.lower()
        calls.append((stem, stdin))
        if stem == "isofilter":
            return ToolRunResult(
                status=RunStatus.SUCCEEDED,
                argv=argv,
                exit_code=0,
                duration_s=0.01,
                stdout="after_iso\n",
                stderr="",
            )
        if stem in ("interpformat", "modelformat"):
            return ToolRunResult(
                status=RunStatus.SUCCEEDED,
                argv=argv,
                exit_code=0,
                duration_s=0.01,
                stdout="after_ifc\n",
                stderr="e2",
            )
        raise AssertionError(f"unexpected tool {stem!r}")

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)

    r = await pipeline("% model\n").run("isofilter").pipe("interpformat").execute(
        stream_intermediate=False,
    )

    assert isinstance(r, ChainResult)
    assert r.stream_intermediate is False
    assert len(r.steps) == 2
    assert r.steps[0].program == "isofilter"
    assert r.steps[1].program == "interpformat"
    assert r.final_stdout == "after_ifc\n"
    assert r.final_stderr == "e2"
    assert calls[0][0] == "isofilter"
    assert calls[0][1] == "% model\n"
    assert calls[1][0] in ("interpformat", "modelformat")
    assert calls[1][1] == "after_iso\n"

    d = r.to_dict()
    assert d["final_stdout"] == "after_ifc\n"
    assert d["stream_intermediate"] is False
    assert len(d["steps"]) == 2


@pytest.mark.asyncio
async def test_pipeline_streaming_run_pipe_chain_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chain(
        self: AsyncToolRunner,
        invs: object,
        *,
        initial_stdin: object = None,
        timeout_s: object = None,
        accumulate_last_stdout: bool = True,
        on_last_stdout_line: object = None,
        last_stdout_path: object = None,
        on_last_stdout_chunk: object = None,
        mace4_interpretation_only_bridges: object = None,
    ) -> tuple[object, ...]:
        assert len(invs) == 2
        return (
            RunStatus.SUCCEEDED,
            0,
            "iso_out\n",
            "",
            ("", ""),
        )

    monkeypatch.setattr(AsyncToolRunner, "run_pipe_chain", fake_chain)

    r = await pipeline("input.").run("mace4").pipe("isofilter").execute(stream_intermediate=True)
    assert r.stream_intermediate is True
    assert r.final_stdout == "iso_out\n"
    assert len(r.steps) == 2


@pytest.mark.asyncio
async def test_pipeline_mace4_then_isofilter_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    n = 0

    async def fake_run(self: AsyncToolRunner, inv: object) -> ToolRunResult:
        nonlocal n
        argv = getattr(inv, "argv", ())
        stdin = getattr(inv, "stdin", None)
        stem = Path(argv[0]).stem.lower()
        n += 1
        if n == 1:
            assert stem == "mace4"
            assert stdin == "input."
            return ToolRunResult(
                status=RunStatus.SUCCEEDED,
                argv=argv,
                exit_code=0,
                duration_s=0.01,
                stdout="interpretation(2, ...).\n",
                stderr="",
            )
        assert stem == "isofilter"
        assert stdin == "interpretation(2, ...).\n"
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=argv,
            exit_code=0,
            duration_s=0.01,
            stdout="iso_out\n",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)

    r = await pipeline("input.").run("mace4").pipe("isofilter").execute(stream_intermediate=False)
    assert r.final_stdout == "iso_out\n"
    assert len(r.steps) == 2
    assert r.steps[0].envelope.program == "mace4"
    assert r.steps[0].envelope.mace4_models is not None
    assert r.steps[0].envelope.mace4_metadata is not None


@pytest.mark.asyncio
async def test_pipeline_three_steps_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(self: AsyncToolRunner, inv: object) -> ToolRunResult:
        argv = getattr(inv, "argv", ())
        stem = Path(argv[0]).stem.lower()
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=argv,
            exit_code=0,
            duration_s=0.01,
            stdout=f"out_{stem}\n",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)

    r = await pipeline("x").run("isofilter").pipe("interpformat").pipe("prooftrans").execute(
        stream_intermediate=False,
    )
    assert len(r.steps) == 3
    assert r.steps[2].program == "prooftrans"
    assert r.final_stdout == "out_prooftrans\n"


def test_pipeline_run_twice_raises() -> None:
    b = pipeline("a").run("isofilter")
    with pytest.raises(ValueError, match="only be used once"):
        b.run("interpformat")


def test_pipeline_pipe_before_run_raises() -> None:
    b = pipeline("a")
    with pytest.raises(ValueError, match="call .run\\(\\) first"):
        b.pipe("isofilter")


@pytest.mark.asyncio
async def test_pipeline_empty_execute_raises() -> None:
    b = PipelineBuilder("x")
    with pytest.raises(ValueError, match="at least one stage"):
        await b.execute()
