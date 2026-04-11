"""Unit tests for pipeline facades and :mod:`pyp9m4.toolkit`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyp9m4 import Isofilter, Prooftrans
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.pipeline_facades import PipelineToolResult
from pyp9m4.runner import AsyncToolRunner, RunStatus, ToolRunResult
from pyp9m4.toolkit import ToolRegistry, ToolRunEnvelope, arun, normalize_tool_name


@pytest.mark.asyncio
async def test_isofilter_arun_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(
        self: AsyncToolRunner,
        inv,  # SubprocessInvocation
    ) -> ToolRunResult:
        assert Path(inv.argv[0]).stem.lower() == "isofilter"
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="% model\n",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    iso = Isofilter()
    r = await iso.arun("a.")
    assert isinstance(r, PipelineToolResult)
    assert r.lifecycle == "succeeded"
    assert r.exit_code == 0
    assert "% model" in r.stdout
    assert r.inspection.looks_like_error is False
    d = r.to_dict()
    assert d["lifecycle"] == "succeeded"
    assert "text" in d and "inspection" in d


@pytest.mark.asyncio
async def test_arun_dispatches_interpformat(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(self: AsyncToolRunner, inv) -> ToolRunResult:
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="[]",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    r = await arun("ifc", "x", options=InterpformatCliOptions(style="portable"))
    assert isinstance(r, ToolRunEnvelope)
    assert r.pipeline is not None
    assert r.pipeline.stdout == "[]"
    assert r.pipeline.lifecycle == "succeeded"


def test_normalize_tool_name_aliases() -> None:
    assert normalize_tool_name("IFC") == "interpformat"
    assert normalize_tool_name("iso") == "isofilter"
    assert normalize_tool_name("pt") == "prooftrans"


def test_normalize_tool_name_unknown() -> None:
    with pytest.raises(ValueError, match="unknown"):
        normalize_tool_name("not-a-tool")


def test_normalize_tool_name_fof_prover9_not_in_arun() -> None:
    with pytest.raises(ValueError, match="not supported by arun"):
        normalize_tool_name("fof_prover9")


@pytest.mark.asyncio
async def test_arun_interpfilter_builds_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, ...]] = []

    async def fake_run(self: AsyncToolRunner, inv) -> ToolRunResult:
        captured.append(inv.argv)
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    await arun(
        "interpfilter",
        "interpretation(1, [], []).\n",
        formulas_file=Path("formulas.txt"),
        test="all_true",
        options={"extra_argv": ("-v",)},
    )
    assert len(captured) == 1
    argv = captured[0]
    assert argv[-2:] == (os.fspath(Path("formulas.txt")), "all_true")
    assert "-v" in argv


@pytest.mark.asyncio
async def test_arun_clausefilter_builds_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, ...]] = []

    async def fake_run(self: AsyncToolRunner, inv) -> ToolRunResult:
        captured.append(inv.argv)
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    await arun(
        "clausefilter",
        "P(x).\n",
        interpretations_file="models.interps",
        test="all_true",
    )
    assert captured[0][-2:] == (os.fspath(Path("models.interps")), "all_true")


def test_tool_registry_get() -> None:
    reg = ToolRegistry()
    assert reg.get("isofilter") is reg.isofilter
    assert reg.get("interpformat") is reg.interpformat
    assert reg.get("prooftrans") is reg.prooftrans
    assert reg.get("clausetester") is reg.clausetester
    assert reg.get("interpfilter") is reg.interpfilter
    assert reg.get("clausefilter") is reg.clausefilter
    assert "isofilter" in reg.registered_pipeline_tools()
    assert "interpfilter" in reg.registered_pipeline_tools()


def test_tool_registry_get_prover9_and_mace4() -> None:
    reg = ToolRegistry()
    assert reg.get("prover9") is reg.prover9
    assert reg.get("mace4") is reg.mace4


@pytest.mark.asyncio
async def test_arun_dispatches_prover9_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_arun(
        self: object,
        input: object,
        *,
        options: object = None,
        **kw: object,
    ) -> object:
        from pyp9m4.prover9_facade import Prover9ProofResult
        from pyp9m4.parsers.prover9 import parse_prover9_output
        from pyp9m4.parsers.prover9_outcome import ProverOutcome

        return Prover9ProofResult(
            parsed=parse_prover9_output(""),
            stdout="ok",
            stderr="",
            exit_code=0,
            lifecycle="succeeded",
            outcome=ProverOutcome.proved,
        )

    monkeypatch.setattr("pyp9m4.prover9_facade.Prover9.arun", fake_arun)
    env = await arun("prover9", "formulas(go).\nend_of_list.\n")
    assert isinstance(env, ToolRunEnvelope)
    assert env.program == "prover9"
    assert env.prover9 is not None
    assert env.prover9.stdout == "ok"
    assert env.raw is not None
    assert env.raw.stdout == "ok"


@pytest.mark.asyncio
async def test_arun_dispatches_mace4_with_raw_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(self: AsyncToolRunner, inv) -> ToolRunResult:
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="interpretation(1, [number=1, seconds=0], []).\n",
            stderr="mace4 stderr",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    env = await arun("mace4", "formulas(assumptions).\nend_of_list.\n")
    assert isinstance(env, ToolRunEnvelope)
    assert env.program == "mace4"
    assert env.raw is not None
    assert env.raw.stdout.startswith("interpretation(")
    assert env.raw.stderr == "mace4 stderr"
    assert env.mace4_models is not None


def test_prooftrans_run_sync_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(self: AsyncToolRunner, inv) -> ToolRunResult:
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.01,
            stdout="% prooftrans\n",
            stderr="",
        )

    monkeypatch.setattr(AsyncToolRunner, "run", fake_run)
    pt = Prooftrans()
    r = pt.run(options=ProofTransCliOptions())
    assert r.lifecycle == "succeeded"
    assert any("prooftrans" in c.lower() for c in r.inspection.percent_comments)
