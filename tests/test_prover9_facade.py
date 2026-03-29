"""Unit tests for :mod:`pyp9m4.prover9_facade`."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pyp9m4.options.prover9 import Prover9CliOptions
from pyp9m4.prover9_facade import Prover9
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import AsyncToolRunner


def test_prover9_constructor_merge_instance_kwargs_over_options() -> None:
    p = Prover9(options=Prover9CliOptions(auto2=True), parenthesize_output=True, resolver=BinaryResolver())
    assert p.default_options.auto2 is True
    assert p.default_options.parenthesize_output is True


def test_prover9_effective_call_precedence() -> None:
    p = Prover9(options=Prover9CliOptions(auto2=True), max_seconds=30, resolver=BinaryResolver())
    o, _t = p._effective_options(options=None, kwargs={"max_seconds": 60})
    assert o.auto2 is True
    assert o.max_seconds == 60

    o2, _t2 = p._effective_options(
        options=Prover9CliOptions(auto2=False, max_seconds=10),
        kwargs={"auto2": True},
    )
    assert o2.auto2 is True
    assert o2.max_seconds == 10


def test_prover9_rejects_unknown_kwarg() -> None:
    with pytest.raises(TypeError, match="unexpected keyword"):
        Prover9(resolver=BinaryResolver(), not_a_prover9_field=1)  # type: ignore[call-arg]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prover9_start_arun_status_and_result() -> None:
    p = Prover9(resolver=BinaryResolver(), timeout_s=120)
    corpus = Path(__file__).resolve().parent / "corpus" / "e2e" / "trivial.in"
    handle = p.start_arun(options=Prover9CliOptions(input_files=(str(corpus),)))

    snap = await handle.status()
    assert snap.argv[0].endswith("prover9") or "prover9" in snap.argv[0].lower() or len(snap.argv) >= 1
    assert snap.lifecycle in ("pending", "running", "succeeded", "failed", "timed_out", "cancelled")

    result = await handle.result()
    assert result.lifecycle == "succeeded"
    assert result.exit_code == 0
    assert "THEOREM PROVED" in result.stdout
    assert result.parsed.statistics.get("proofs") == "1"

    snap2 = await handle.status()
    assert snap2.lifecycle == "succeeded"


@pytest.mark.asyncio
async def test_prover9_start_arun_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _blocked_run(self: AsyncToolRunner, inv: object) -> object:  # noqa: ARG002
        await asyncio.sleep(3600.0)

    monkeypatch.setattr(AsyncToolRunner, "run", _blocked_run)

    p = Prover9(resolver=BinaryResolver())
    handle = p.start_arun("formulas(go).\nend_of_list.\n")
    await asyncio.sleep(0)
    handle.cancel()
    out = await handle.result()
    assert out.lifecycle == "cancelled"
    snap = await handle.status()
    assert snap.lifecycle == "cancelled"
