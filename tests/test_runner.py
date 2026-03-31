"""Tests for :mod:`pyp9m4.runner`."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from pyp9m4.runner import (
    AsyncToolRunner,
    RunStatus,
    StderrLine,
    StdoutLine,
    SubprocessInvocation,
    SyncToolRunner,
    ToolRunResult,
    run_sync,
    stream_events_sync,
)


def _py(args: str) -> tuple[str, ...]:
    return (sys.executable, "-c", args)


@pytest.mark.asyncio
async def test_run_success_echo() -> None:
    r = AsyncToolRunner()
    inv = SubprocessInvocation(argv=_py("print('hi')"))
    res = await r.run(inv)
    assert res.status == RunStatus.SUCCEEDED
    assert res.exit_code == 0
    assert res.stdout.strip() == "hi"
    assert res.stderr == ""


@pytest.mark.asyncio
async def test_run_exit_nonzero() -> None:
    r = AsyncToolRunner()
    inv = SubprocessInvocation(argv=_py("import sys; sys.exit(3)"))
    res = await r.run(inv)
    assert res.status == RunStatus.FAILED
    assert res.exit_code == 3


@pytest.mark.asyncio
async def test_run_timeout() -> None:
    r = AsyncToolRunner()
    inv = SubprocessInvocation(
        argv=_py("import time; time.sleep(10)"),
        timeout_s=0.3,
    )
    res = await r.run(inv)
    assert res.status == RunStatus.TIMED_OUT
    assert res.exit_code is not None


@pytest.mark.asyncio
async def test_run_cancel() -> None:
    r = AsyncToolRunner()
    inv = SubprocessInvocation(argv=_py("import time; time.sleep(10)"))

    task = asyncio.create_task(r.run(inv))
    await asyncio.sleep(0.05)
    task.cancel()
    res = await task
    assert res.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_stream_events_on_complete() -> None:
    r = AsyncToolRunner()
    inv = SubprocessInvocation(argv=_py("print('ok')"))
    seen: list[ToolRunResult] = []

    async def on_complete(res: ToolRunResult) -> None:
        seen.append(res)

    out: list[object] = []
    async for ev in r.stream_events(inv, on_complete=on_complete):
        out.append(ev)

    assert len(seen) == 1
    assert seen[0].status == RunStatus.SUCCEEDED
    assert seen[0].stdout.strip() == "ok"
    assert StdoutLine("ok") in out


@pytest.mark.asyncio
async def test_stream_events_lines_and_parse_hook() -> None:
    r = AsyncToolRunner()
    code = (
        "import sys\n"
        "print('o1')\n"
        "print('e1', file=sys.stderr)\n"
        "print('o2')\n"
    )
    inv = SubprocessInvocation(argv=_py(code))

    async def hook(e: object):
        if isinstance(e, StdoutLine) and e.text == "o1":
            yield "parsed-o1"

    out: list[object] = []
    async for ev in r.stream_events(inv, parse_hook=hook):
        out.append(ev)

    assert StdoutLine("o1") in out
    assert "parsed-o1" in out
    assert StderrLine("e1") in out
    assert StdoutLine("o2") in out


@pytest.mark.asyncio
async def test_tee_stdout(tmp_path: Path) -> None:
    tee = tmp_path / "out.log"
    r = AsyncToolRunner()
    inv = SubprocessInvocation(argv=_py("print('x')"), tee_stdout_path=tee)
    res = await r.run(inv)
    assert res.status == RunStatus.SUCCEEDED
    assert tee.read_text(encoding="utf-8").strip() == "x"


def test_run_sync() -> None:
    inv = SubprocessInvocation(argv=_py("print(42)"))
    res = run_sync(inv)
    assert isinstance(res, ToolRunResult)
    assert res.stdout.strip() == "42"


@pytest.mark.asyncio
async def test_run_sync_with_running_event_loop() -> None:
    """Sync wrapper must not call asyncio.run on a thread that already has a loop."""
    inv = SubprocessInvocation(argv=_py("print(99)"))
    res = run_sync(inv)
    assert res.stdout.strip() == "99"


def test_stream_events_sync() -> None:
    code = "import sys\nprint('a')\nprint('b', file=sys.stderr)\n"
    inv = SubprocessInvocation(argv=_py(code))
    events = stream_events_sync(inv)
    assert StdoutLine("a") in events
    assert StderrLine("b") in events


def test_stream_events_sync_parse_hook() -> None:
    inv = SubprocessInvocation(argv=_py("print('x')"))

    async def hook(e: object):
        if isinstance(e, StdoutLine) and e.text == "x":
            yield "extra"

    events = stream_events_sync(inv, parse_hook=hook)
    assert StdoutLine("x") in events
    assert "extra" in events


def test_sync_tool_runner() -> None:
    r = SyncToolRunner()
    inv = SubprocessInvocation(argv=_py("print(3)"))
    res = r.run(inv)
    assert res.stdout.strip() == "3"
    inv2 = SubprocessInvocation(argv=_py("print('z')"))
    assert StdoutLine("z") in r.stream_events(inv2)


@pytest.mark.asyncio
async def test_stdin_string() -> None:
    r = AsyncToolRunner()
    code = "import sys; print(sys.stdin.read().strip())"
    inv = SubprocessInvocation(argv=_py(code), stdin="hello\n")
    res = await r.run(inv)
    assert res.stdout.strip() == "hello"
