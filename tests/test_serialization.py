"""Tests for :mod:`pyp9m4.serialization` and :meth:`~object.to_dict` on public dataclasses."""

from __future__ import annotations

import base64
from pathlib import Path

from pyp9m4 import ProverOutcome, Prover9ProofResult
from pyp9m4.parsers.prover9 import Prover9Parsed
from pyp9m4.runner import RunStatus, SubprocessInvocation, ToolRunResult
from pyp9m4.serialization import dataclass_to_json_dict, jsonify_for_api


def test_jsonify_for_api_nested() -> None:
    assert jsonify_for_api((1, (2, 3))) == [1, [2, 3]]
    p = Path("a", "b", "c")
    assert jsonify_for_api({"a": p}) == {"a": str(p)}


def test_tool_run_result_to_dict() -> None:
    r = ToolRunResult(
        status=RunStatus.SUCCEEDED,
        argv=("p9",),
        exit_code=0,
        duration_s=0.1,
        stdout="ok",
        stderr="",
        command_cwd=Path("tmp"),
    )
    d = r.to_dict()
    assert d == dataclass_to_json_dict(r)
    assert d["status"] == "succeeded"
    assert d["argv"] == ["p9"]
    assert d["command_cwd"] == str(Path("tmp"))


def test_subprocess_invocation_to_dict_paths_and_bytes() -> None:
    inv = SubprocessInvocation(
        argv=("mace4",),
        cwd=Path("."),
        stdin=b"\xff\x00",
        tee_stdout_path=Path("out.log"),
    )
    d = inv.to_dict()
    assert d["cwd"] == "."
    assert d["stdin"] == base64.b64encode(b"\xff\x00").decode("ascii")
    assert d["tee_stdout_path"] == "out.log"


def test_prover9_proof_result_to_dict() -> None:
    parsed = Prover9Parsed(
        sections={},
        statistics={},
        proof_segments=(),
        exit_phrases=("THEOREM PROVED",),
        warnings=(),
    )
    pr = Prover9ProofResult(
        parsed=parsed,
        stdout="x",
        stderr="",
        exit_code=0,
        lifecycle="succeeded",
        outcome=ProverOutcome.proved,
    )
    d = pr.to_dict()
    assert d["lifecycle"] == "succeeded"
    assert d["outcome"] == "proved"
    assert d["parsed"]["exit_phrases"] == ["THEOREM PROVED"]
