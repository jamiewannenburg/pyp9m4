"""Tests for :mod:`pyp9m4.pipe` and pipe-chain tee behavior."""

from __future__ import annotations

import asyncio
import sys

import pytest

from pyp9m4.io_kinds import IOKind
from pyp9m4.pipe import PipeRunResult, Stage, tool_stdio_kinds
from pyp9m4.runner import AsyncToolRunner, RunStatus, SubprocessInvocation


def _py(args: str) -> tuple[str, ...]:
    return (sys.executable, "-c", args)


def test_tool_stdio_kinds_mace4() -> None:
    a, b = tool_stdio_kinds("mace4")
    assert a == IOKind.THEORY
    assert b == IOKind.INTERPRETATIONS


def test_tool_stdio_kinds_unknown() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        tool_stdio_kinds("not_a_ladr_tool")


def test_stage_type_mismatch() -> None:
    s = Stage.source("x", kind=IOKind.THEORY)
    inv = SubprocessInvocation(argv=_py("print(1)"))
    with pytest.raises(TypeError, match="type mismatch"):
        s.with_step(inv, produces=IOKind.PROOFS, expects=IOKind.INTERPRETATIONS)


def test_stage_output_two_step() -> None:
    code1 = "import sys; print(sys.stdin.read().strip())"
    code2 = "import sys; print(sys.stdin.read().strip().upper())"
    st = (
        Stage.source("hi", kind=IOKind.LADR_TEXT)
        .with_step(SubprocessInvocation(argv=_py(code1)), produces=IOKind.LADR_TEXT)
        .with_step(SubprocessInvocation(argv=_py(code2)), produces=IOKind.LADR_TEXT)
    )
    res = st.output()
    assert isinstance(res, PipeRunResult)
    assert res.ok
    assert res.stdout.strip() == "HI"


def test_stage_stream_lines() -> None:
    code = "import sys; print('a'); print('b')"
    st = Stage.source("", kind=IOKind.LADR_TEXT).with_step(
        SubprocessInvocation(argv=_py(code)),
        produces=IOKind.LADR_TEXT,
    )
    assert list(st.stream()) == ["a", "b"]


def test_stage_stream_chunks() -> None:
    code = "print('ok', end='')"
    st = Stage.source("", kind=IOKind.LADR_TEXT).with_step(
        SubprocessInvocation(argv=_py(code)),
        produces=IOKind.LADR_TEXT,
    )
    chunks = list(st.stream(lines=False))
    assert "".join(chunks).strip() == "ok"


@pytest.mark.asyncio
async def test_stage_aoutput() -> None:
    st = Stage.source("42", kind=IOKind.LADR_TEXT).with_step(
        SubprocessInvocation(argv=_py("import sys; print(int(sys.stdin.read()) * 2)")),
        produces=IOKind.LADR_TEXT,
    )
    res = await st.aoutput()
    assert res.stdout.strip() == "84"


@pytest.mark.asyncio
async def test_stage_astream() -> None:
    code = "print('z')"
    st = Stage.source("", kind=IOKind.LADR_TEXT).with_step(
        SubprocessInvocation(argv=_py(code)),
        produces=IOKind.LADR_TEXT,
    )
    out = [x async for x in st.astream()]
    assert out == ["z"]


def test_stage_output_file_tee(tmp_path) -> None:
    tee = tmp_path / "captured.txt"
    code = "print('tee-me')"
    st = Stage.source("", kind=IOKind.LADR_TEXT).with_step(
        SubprocessInvocation(argv=_py(code)),
        produces=IOKind.LADR_TEXT,
        output_file=tee,
    )
    res = st.output()
    assert res.ok
    assert res.stdout.strip() == "tee-me"
    assert tee.read_text(encoding="utf-8").strip() == "tee-me"


@pytest.mark.asyncio
async def test_run_pipe_chain_tee_intermediate(tmp_path) -> None:
    tee = tmp_path / "mid.out"
    code1 = "print('ab')"
    code2 = "import sys; print(sys.stdin.read().strip().upper())"
    invs = [
        SubprocessInvocation(argv=_py(code1), tee_stdout_path=tee),
        SubprocessInvocation(argv=_py(code2)),
    ]
    r = AsyncToolRunner()
    st, code, out, err, _per = await r.run_pipe_chain(invs, initial_stdin=None)
    assert st == RunStatus.SUCCEEDED
    assert out.strip() == "AB"
    assert "ab" in tee.read_text(encoding="utf-8").replace("\r\n", "\n")
