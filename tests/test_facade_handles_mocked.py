"""Unit tests for facade job handles: lifecycle and status snapshots without LADR binaries."""

from __future__ import annotations

import inspect

import pytest

from pyp9m4.mace4_facade import Mace4
from pyp9m4.options.mace4 import Mace4CliOptions
from pyp9m4.prover9_facade import Prover9
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import AsyncToolRunner, RunStatus, StdoutLine, ToolRunResult


@pytest.mark.asyncio
async def test_prover9_proof_handle_status_transitions_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(self: AsyncToolRunner, inv: object) -> ToolRunResult:  # noqa: ARG002
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=getattr(inv, "argv", ()),
            exit_code=0,
            duration_s=0.01,
            stdout="THEOREM PROVED\n",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", _fake_run)
    p = Prover9(resolver=BinaryResolver())
    handle = p.start_arun("formulas(go).\nend_of_list.\n")
    snap0 = await handle.status()
    assert snap0.lifecycle in ("pending", "running")

    result = await handle.result()
    assert result.lifecycle == "succeeded"
    assert result.exit_code == 0
    assert "THEOREM PROVED" in result.stdout

    snap1 = await handle.status()
    assert snap1.lifecycle == "succeeded"
    assert snap1.exit_code == 0
    assert snap1.duration_s is not None


@pytest.mark.asyncio
async def test_prover9_proof_handle_status_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(self: AsyncToolRunner, inv: object) -> ToolRunResult:  # noqa: ARG002
        return ToolRunResult(
            status=RunStatus.FAILED,
            argv=getattr(inv, "argv", ()),
            exit_code=2,
            duration_s=0.01,
            stdout="",
            stderr="syntax error\n",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", _fake_run)
    p = Prover9(resolver=BinaryResolver())
    handle = p.start_arun("bad")
    await handle.wait()
    snap = await handle.status()
    assert snap.lifecycle == "failed"
    assert snap.exit_code == 2
    assert "syntax" in snap.stderr_tail


@pytest.mark.asyncio
async def test_mace4_search_handle_status_and_models_mocked_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = [
        "interpretation( 2, [",
        "   function = c1 = 0,",
        "]).",
    ]

    async def _fake_stream(
        self: AsyncToolRunner,
        inv: object,
        *,
        parse_hook: object = None,
        on_complete: object = None,
    ):
        if parse_hook is not None:
            for line in lines:
                ev = StdoutLine(line)
                async for x in parse_hook(ev):  # type: ignore[operator]
                    yield x
        if on_complete is not None:
            res = ToolRunResult(
                status=RunStatus.SUCCEEDED,
                argv=getattr(inv, "argv", ()),
                exit_code=0,
                duration_s=0.02,
                stdout="\n".join(lines),
                stderr="mace4 note\n",
            )
            oc = on_complete(res)
            if inspect.isawaitable(oc):
                await oc

    monkeypatch.setattr(AsyncToolRunner, "stream_events", _fake_stream)

    m = Mace4(
        resolver=BinaryResolver(),
        options=Mace4CliOptions(domain_size=2, end_size=5, increment=1),
    )
    handle = m.start_amodels("formulas(go).\nend_of_list.\n")

    snap_early = await handle.status()
    assert snap_early.lifecycle in ("pending", "running")
    assert snap_early.current_size_range == (2, 5)
    assert snap_early.domain_increment == 1

    await handle.wait()
    final = await handle.status()
    assert final.lifecycle == "succeeded"
    assert final.models_found == 1
    assert final.last_domain_size == 2
    assert final.exit_code == 0
    assert "note" in final.stderr_tail

    models = [x async for x in handle.amodels()]
    assert len(models) == 1
    assert models[0].domain_size == 2


@pytest.mark.asyncio
async def test_mace4_start_amodels_isomorphic_pipeline_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interp_block = """interpretation( 2, [
   function = c1 = 0,
])."""

    async def _fake_pipeline(
        self: Mace4,
        stdin: str | bytes | None,  # noqa: ARG002
        opts: object,  # noqa: ARG002
        *,
        timeout_s: float | None,  # noqa: ARG002
    ):
        from pyp9m4.parsers.mace4 import parse_mace4_output

        parsed = parse_mace4_output(interp_block)
        return RunStatus.SUCCEEDED, 0, interp_block, "", parsed.interpretations

    monkeypatch.setattr(Mace4, "_arun_isomorphic_pipeline", _fake_pipeline)

    m = Mace4(resolver=BinaryResolver(), eliminate_isomorphic=True)
    handle = m.start_amodels("x")
    await handle.wait()
    snap = await handle.status()
    assert snap.lifecycle == "succeeded"
    assert snap.models_found == 1
    models = [x async for x in handle.amodels()]
    assert len(models) == 1
