"""Async subprocess runner for LADR tools: timeouts, cancellation, and layered streaming."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RunStatus(enum.Enum):
    """Lifecycle state of a subprocess run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ToolRunResult:
    """Immutable outcome of a finished (or aborted) tool invocation."""

    status: RunStatus
    argv: tuple[str, ...]
    exit_code: int | None
    duration_s: float
    stdout: str = ""
    stderr: str = ""
    command_cwd: Path | None = None


@dataclass(frozen=True, slots=True)
class StdoutLine:
    """Layer A: one decoded line from the child stdout (newline stripped)."""

    text: str


@dataclass(frozen=True, slots=True)
class StderrLine:
    """Layer A: one decoded line from the child stderr (newline stripped)."""

    text: str


# Layer B: domain parsers may emit additional event types via ``parse_hook`` in :meth:`AsyncToolRunner.stream_events`.
StreamEvent = StdoutLine | StderrLine


@dataclass(frozen=True, slots=True)
class SubprocessInvocation:
    """Arguments for :class:`AsyncToolRunner` (executable + args, I/O, limits)."""

    argv: tuple[str, ...]
    cwd: Path | str | None = None
    env: Mapping[str, str] | None = None
    stdin: str | bytes | None = None
    timeout_s: float | None = None
    text: bool = True
    encoding: str = "utf-8"
    errors: str = "replace"
    tee_stdout_path: Path | str | None = None
    tee_stderr_path: Path | str | None = None


def _to_path(p: Path | str | None) -> Path | None:
    if p is None:
        return None
    return Path(p) if isinstance(p, str) else p


def _stdin_bytes(stdin: str | bytes | None, *, encoding: str, errors: str) -> bytes | None:
    if stdin is None:
        return None
    if isinstance(stdin, bytes):
        return stdin
    return stdin.encode(encoding, errors=errors)


async def _async_terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(ProcessLookupError, asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)


class AsyncToolRunner:
    """Run external tools with asyncio: capture, tee, timeouts, cancellation, streaming."""

    async def run(self, inv: SubprocessInvocation) -> ToolRunResult:
        """Run to completion; capture stdout/stderr as strings (when ``inv.text`` is True).

        If the calling :class:`asyncio.Task` is cancelled, the child process is terminated
        and the returned :class:`ToolRunResult` has :attr:`RunStatus.CANCELLED` (cancellation
        is not re-raised so callers get a structured outcome).
        """
        out_buf: list[str] = []
        err_buf: list[str] = []

        async def on_out(line: str) -> None:
            out_buf.append(line)

        async def on_err(line: str) -> None:
            err_buf.append(line)

        meta = await self._execute(inv, line_handlers=(on_out, on_err))
        return ToolRunResult(
            status=meta.status,
            argv=meta.argv,
            exit_code=meta.exit_code,
            duration_s=meta.duration_s,
            stdout="\n".join(out_buf),
            stderr="\n".join(err_buf),
            command_cwd=meta.command_cwd,
        )

    async def stream_events(
        self,
        inv: SubprocessInvocation,
        *,
        parse_hook: Callable[[Any], AsyncIterator[Any]] | None = None,
    ) -> AsyncIterator[Any]:
        """Yield layer-A line events (and optional layer-B events from ``parse_hook``).

        For each layer-A chunk ``e``, when ``parse_hook`` is set, the runner also yields
        everything produced by ``async for x in parse_hook(e): ...``.
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()

        async def emit_layer_a(e: StreamEvent) -> None:
            await queue.put(e)
            if parse_hook is not None:
                async for x in parse_hook(e):
                    await queue.put(x)

        async def on_out(line: str) -> None:
            await emit_layer_a(StdoutLine(line))

        async def on_err(line: str) -> None:
            await emit_layer_a(StderrLine(line))

        async def runner_coro() -> ToolRunResult:
            try:
                return await self._execute(inv, line_handlers=(on_out, on_err))
            finally:
                await queue.put(sentinel)

        task = asyncio.create_task(runner_coro())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            else:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        if task.cancelled():
            raise asyncio.CancelledError
        exc = task.exception()
        if exc is not None:
            raise exc

    async def _execute(
        self,
        inv: SubprocessInvocation,
        *,
        line_handlers: tuple[
            Callable[[str], Awaitable[None]],
            Callable[[str], Awaitable[None]],
        ],
    ) -> ToolRunResult:
        if not inv.argv:
            raise ValueError("argv must be non-empty (executable first)")

        cwd: Path | None = None
        if inv.cwd is not None:
            cwd = Path(inv.cwd).resolve()

        tee_out = _to_path(inv.tee_stdout_path)
        tee_err = _to_path(inv.tee_stderr_path)
        tee_out_f = tee_err_f = None
        if tee_out is not None:
            tee_out.parent.mkdir(parents=True, exist_ok=True)
            tee_out_f = tee_out.open("a", encoding=inv.encoding, errors=inv.errors)
        if tee_err is not None:
            tee_err.parent.mkdir(parents=True, exist_ok=True)
            tee_err_f = tee_err.open("a", encoding=inv.encoding, errors=inv.errors)

        stdin_data = _stdin_bytes(inv.stdin, encoding=inv.encoding, errors=inv.errors)
        argv_os = tuple(os.fsdecode(os.fsencode(a)) for a in inv.argv)

        start = time.perf_counter()
        status = RunStatus.FAILED
        exit_code: int | None = None
        proc: asyncio.subprocess.Process | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv_os,
                stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.fspath(cwd) if cwd is not None else None,
                env=dict(inv.env) if inv.env is not None else None,
            )

            async def pump_stdout() -> None:
                assert proc is not None and proc.stdout is not None
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode(inv.encoding, errors=inv.errors).rstrip("\r\n")
                    if tee_out_f is not None:
                        tee_out_f.write(line + "\n")
                        tee_out_f.flush()
                    await line_handlers[0](line)

            async def pump_stderr() -> None:
                assert proc is not None and proc.stderr is not None
                while True:
                    raw = await proc.stderr.readline()
                    if not raw:
                        break
                    line = raw.decode(inv.encoding, errors=inv.errors).rstrip("\r\n")
                    if tee_err_f is not None:
                        tee_err_f.write(line + "\n")
                        tee_err_f.flush()
                    await line_handlers[1](line)

            async def write_stdin() -> None:
                assert proc is not None and proc.stdin is not None
                assert stdin_data is not None
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.stdin.wait_closed()

            pump_tasks: list[asyncio.Task[None]] = [
                asyncio.create_task(pump_stdout()),
                asyncio.create_task(pump_stderr()),
            ]
            if stdin_data is not None:
                pump_tasks.append(asyncio.create_task(write_stdin()))

            wait_task = asyncio.create_task(proc.wait())

            try:
                if inv.timeout_s is not None:
                    try:
                        await asyncio.wait_for(wait_task, timeout=inv.timeout_s)
                    except asyncio.TimeoutError:
                        status = RunStatus.TIMED_OUT
                        await _async_terminate(proc)
                        if not wait_task.done():
                            with contextlib.suppress(Exception):
                                await wait_task
                else:
                    await wait_task
            except asyncio.CancelledError:
                status = RunStatus.CANCELLED
                await _async_terminate(proc)
                if not wait_task.done():
                    with contextlib.suppress(Exception):
                        await wait_task
                for t in pump_tasks:
                    t.cancel()
                await asyncio.gather(*pump_tasks, return_exceptions=True)
                exit_code = proc.returncode
                duration = time.perf_counter() - start
                return ToolRunResult(
                    status=status,
                    argv=tuple(inv.argv),
                    exit_code=exit_code,
                    duration_s=duration,
                    command_cwd=cwd,
                )

            if status != RunStatus.TIMED_OUT:
                await asyncio.gather(*pump_tasks)
                exit_code = proc.returncode
                status = RunStatus.SUCCEEDED if exit_code == 0 else RunStatus.FAILED
            else:
                for t in pump_tasks:
                    t.cancel()
                await asyncio.gather(*pump_tasks, return_exceptions=True)
                exit_code = proc.returncode

        finally:
            if tee_out_f is not None:
                tee_out_f.close()
            if tee_err_f is not None:
                tee_err_f.close()

        duration = time.perf_counter() - start
        return ToolRunResult(
            status=status,
            argv=tuple(inv.argv),
            exit_code=exit_code,
            duration_s=duration,
            command_cwd=cwd,
        )


def run_sync(inv: SubprocessInvocation) -> ToolRunResult:
    """Blocking wrapper around :meth:`AsyncToolRunner.run` (uses :func:`asyncio.run`)."""
    return asyncio.run(AsyncToolRunner().run(inv))