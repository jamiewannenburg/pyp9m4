"""Unit tests for pipeline facades and :mod:`pyp9m4.toolkit`."""

from __future__ import annotations

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


def test_tool_registry_get() -> None:
    reg = ToolRegistry()
    assert reg.get("isofilter") is reg.isofilter
    assert reg.get("interpformat") is reg.interpformat
    assert reg.get("prooftrans") is reg.prooftrans
    assert "isofilter" in reg.registered_pipeline_tools()


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
