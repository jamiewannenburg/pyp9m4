"""Async subprocess runner for LADR tools: timeouts, cancellation, and layered streaming."""

from __future__ import annotations

import asyncio
import codecs
import concurrent.futures
import contextlib
import enum
import inspect
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pyp9m4.serialization import dataclass_to_json_dict

T = TypeVar("T")


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

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly run outcome (:class:`RunStatus` as string, paths as ``str``)."""
        return dataclass_to_json_dict(self)


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

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly invocation (paths as ``str``, ``bytes`` stdin as base64)."""
        return dataclass_to_json_dict(self)


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


def _decode_lines(data: bytes, *, encoding: str, errors: str) -> list[str]:
    if not data:
        return []
    return data.decode(encoding, errors=errors).splitlines()


def _loop_debug_name() -> str:
    with contextlib.suppress(RuntimeError):
        loop = asyncio.get_running_loop()
        return type(loop).__name__
    return "<no running loop>"


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
        on_complete: Callable[[ToolRunResult], Awaitable[None] | None] | None = None,
    ) -> AsyncIterator[Any]:
        """Yield layer-A line events (and optional layer-B events from ``parse_hook``).

        For each layer-A chunk ``e``, when ``parse_hook`` is set, the runner also yields
        everything produced by ``async for x in parse_hook(e): ...``.

        If ``on_complete`` is set, it is invoked with the :class:`ToolRunResult` after the
        subprocess finishes and before the stream sentinel is queued (awaited if it returns
        a coroutine).
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        sentinel = object()
        out_buf: list[str] = []
        err_buf: list[str] = []

        async def emit_layer_a(e: StreamEvent) -> None:
            await queue.put(e)
            if parse_hook is not None:
                async for x in parse_hook(e):
                    await queue.put(x)

        async def on_out(line: str) -> None:
            out_buf.append(line)
            await emit_layer_a(StdoutLine(line))

        async def on_err(line: str) -> None:
            err_buf.append(line)
            await emit_layer_a(StderrLine(line))

        async def runner_coro() -> ToolRunResult:
            res: ToolRunResult | None = None
            try:
                meta = await self._execute(inv, line_handlers=(on_out, on_err))
                res = ToolRunResult(
                    status=meta.status,
                    argv=meta.argv,
                    exit_code=meta.exit_code,
                    duration_s=meta.duration_s,
                    stdout="\n".join(out_buf),
                    stderr="\n".join(err_buf),
                    command_cwd=meta.command_cwd,
                )
                return res
            finally:
                try:
                    if res is not None and on_complete is not None:
                        oc = on_complete(res)
                        if inspect.isawaitable(oc):
                            await oc
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

    async def run_pipe_chain(
        self,
        invs: list[SubprocessInvocation],
        *,
        initial_stdin: str | bytes | None,
        timeout_s: float | None = None,
        accumulate_last_stdout: bool = True,
        on_last_stdout_line: Callable[[str], Awaitable[None] | None] | None = None,
        last_stdout_path: Path | str | None = None,
        on_last_stdout_chunk: Callable[[bytes], Awaitable[None] | None] | None = None,
    ) -> tuple[RunStatus, int | None, str, str, tuple[str, ...]]:
        """Run ``invs[0] | invs[1] | ...`` with byte-sized pumps (no full intermediate buffers).

        The last process stdout is consumed line-by-line unless ``on_last_stdout_chunk`` is set,
        in which case it is read in fixed-size chunks (for incremental decoding / parsing).

        Returns ``(status, exit_code, last_stdout, last_stderr, stderr_per_inv)``.
        ``last_stderr`` is the last process's stderr only; ``stderr_per_inv`` has one string per
        invocation (possibly empty).
        """
        if not invs:
            raise ValueError("run_pipe_chain: invs must be non-empty")

        encoding = invs[0].encoding
        errors = invs[0].errors

        eff_timeout = timeout_s
        if eff_timeout is None:
            timeouts = [inv.timeout_s for inv in invs if inv.timeout_s is not None]
            eff_timeout = max(timeouts) if timeouts else None

        stdin_data = _stdin_bytes(initial_stdin, encoding=encoding, errors=errors)
        procs: list[asyncio.subprocess.Process] = []

        async def _terminate_all() -> None:
            for p in procs:
                await _async_terminate(p)

        try:
            try:
                for i, inv in enumerate(invs):
                    argv_os = tuple(os.fsdecode(os.fsencode(a)) for a in inv.argv)
                    cwd_p: str | None = None
                    if inv.cwd is not None:
                        cwd_p = os.fspath(Path(inv.cwd).resolve())
                    if i > 0:
                        stdin_arg = asyncio.subprocess.PIPE
                    elif stdin_data is not None:
                        stdin_arg = asyncio.subprocess.PIPE
                    else:
                        stdin_arg = asyncio.subprocess.DEVNULL
                    proc = await asyncio.create_subprocess_exec(
                        *argv_os,
                        stdin=stdin_arg,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd_p,
                        env=dict(inv.env) if inv.env is not None else None,
                    )
                    procs.append(proc)
            except NotImplementedError:
                raise RuntimeError(
                    "asyncio subprocess transport unavailable for pipe chain. "
                    "On Windows, use a Proactor event loop, or set stream_intermediate=False "
                    "on the pipeline builder."
                ) from None

            n = len(procs)
            assert n == len(invs)

            async def feed_first() -> None:
                if stdin_data is None or procs[0].stdin is None:
                    return
                w = procs[0].stdin
                w.write(stdin_data)
                await w.drain()
                w.close()
                await w.wait_closed()

            async def pump_to_next(i: int) -> None:
                src = procs[i].stdout
                dst = procs[i + 1].stdin
                assert src is not None and dst is not None
                try:
                    while True:
                        chunk = await src.read(65536)
                        if not chunk:
                            break
                        dst.write(chunk)
                        await dst.drain()
                finally:
                    dst.close()
                    with contextlib.suppress(Exception):
                        await dst.wait_closed()

            async def drain_stderr_idx(i: int) -> str:
                p = procs[i]
                assert p.stderr is not None
                lines: list[str] = []
                while True:
                    raw = await p.stderr.readline()
                    if not raw:
                        break
                    lines.append(raw.decode(encoding, errors=errors).rstrip("\r\n"))
                return "\n".join(lines)

            async def drain_last_stdout_lines() -> str:
                p = procs[-1]
                assert p.stdout is not None
                acc: list[str] = []
                f = None
                if last_stdout_path is not None:
                    pth = Path(last_stdout_path)
                    pth.parent.mkdir(parents=True, exist_ok=True)
                    f = pth.open("a", encoding=encoding, errors=errors)
                try:
                    while True:
                        raw = await p.stdout.readline()
                        if not raw:
                            break
                        line = raw.decode(encoding, errors=errors).rstrip("\r\n")
                        if accumulate_last_stdout:
                            acc.append(line)
                        if on_last_stdout_line is not None:
                            r = on_last_stdout_line(line)
                            if inspect.isawaitable(r):
                                await r
                        if f is not None:
                            f.write(line + "\n")
                            f.flush()
                finally:
                    if f is not None:
                        f.close()
                return "\n".join(acc) if accumulate_last_stdout else ""

            async def drain_last_stdout_chunks() -> str:
                p = procs[-1]
                assert p.stdout is not None
                decoder = codecs.getincrementaldecoder(encoding)(errors)
                text_parts: list[str] = []
                f = None
                if last_stdout_path is not None:
                    pth = Path(last_stdout_path)
                    pth.parent.mkdir(parents=True, exist_ok=True)
                    f = pth.open("ab")
                try:
                    while True:
                        chunk = await p.stdout.read(65536)
                        if not chunk:
                            break
                        if on_last_stdout_chunk is not None:
                            r = on_last_stdout_chunk(chunk)
                            if inspect.isawaitable(r):
                                await r
                        if accumulate_last_stdout:
                            text_parts.append(decoder.decode(chunk))
                        if f is not None:
                            f.write(chunk)
                            f.flush()
                    text_parts.append(decoder.decode(b"", final=True))
                    if on_last_stdout_chunk is not None:
                        r = on_last_stdout_chunk(b"")
                        if inspect.isawaitable(r):
                            await r
                finally:
                    if f is not None:
                        f.close()
                return "".join(text_parts) if accumulate_last_stdout else ""

            all_tasks: list[asyncio.Task[Any]] = [
                asyncio.create_task(feed_first()),
                *[asyncio.create_task(pump_to_next(i)) for i in range(n - 1)],
                *[asyncio.create_task(drain_stderr_idx(i)) for i in range(n)],
                asyncio.create_task(
                    drain_last_stdout_chunks()
                    if on_last_stdout_chunk is not None
                    else drain_last_stdout_lines()
                ),
            ]
            try:
                if eff_timeout is not None:
                    results = await asyncio.wait_for(asyncio.gather(*all_tasks), timeout=eff_timeout)
                else:
                    results = await asyncio.gather(*all_tasks)
            except asyncio.TimeoutError:
                await _terminate_all()
                return (
                    RunStatus.TIMED_OUT,
                    None,
                    "",
                    "",
                    tuple("" for _ in invs),
                )

            await asyncio.gather(*(p.wait() for p in procs))

            stderr_per_inv = tuple(results[n : 2 * n])
            last_stdout_str = results[2 * n]
            last_stderr = stderr_per_inv[-1]

            exit_codes = [p.returncode for p in procs]
            ok = all(c == 0 for c in exit_codes if c is not None)
            status = RunStatus.SUCCEEDED if ok else RunStatus.FAILED
            exit_code = exit_codes[-1]

            return (status, exit_code, last_stdout_str, last_stderr, stderr_per_inv)
        except asyncio.CancelledError:
            await _terminate_all()
            raise
        except Exception:
            await _terminate_all()
            raise

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
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv_os,
                    stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.fspath(cwd) if cwd is not None else None,
                    env=dict(inv.env) if inv.env is not None else None,
                )
            except NotImplementedError:
                # Windows selector-based loops cannot create subprocess transports.
                # Fall back to a thread-executed sync subprocess path.
                res = await self._execute_blocking_fallback(
                    inv=inv,
                    argv_os=argv_os,
                    cwd=cwd,
                    stdin_data=stdin_data,
                    line_handlers=line_handlers,
                    tee_out_f=tee_out_f,
                    tee_err_f=tee_err_f,
                    start=start,
                )
                return res

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

    async def _execute_blocking_fallback(
        self,
        *,
        inv: SubprocessInvocation,
        argv_os: tuple[str, ...],
        cwd: Path | None,
        stdin_data: bytes | None,
        line_handlers: tuple[
            Callable[[str], Awaitable[None]],
            Callable[[str], Awaitable[None]],
        ],
        tee_out_f: Any,
        tee_err_f: Any,
        start: float,
    ) -> ToolRunResult:
        holder: dict[str, subprocess.Popen[bytes]] = {}

        def _run_blocking() -> tuple[int | None, bool, bytes, bytes]:
            proc = subprocess.Popen(
                argv_os,
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.fspath(cwd) if cwd is not None else None,
                env=dict(inv.env) if inv.env is not None else None,
            )
            holder["proc"] = proc
            try:
                out_b, err_b = proc.communicate(input=stdin_data, timeout=inv.timeout_s)
                return proc.returncode, False, out_b or b"", err_b or b""
            except subprocess.TimeoutExpired as exc:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    out_b, err_b = proc.communicate(timeout=3.0)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    out_b, err_b = proc.communicate()
                if exc.stdout:
                    out_b = exc.stdout + (out_b or b"")
                if exc.stderr:
                    err_b = exc.stderr + (err_b or b"")
                return proc.returncode, True, out_b or b"", err_b or b""

        task = asyncio.create_task(asyncio.to_thread(_run_blocking))
        try:
            exit_code, timed_out, out_b, err_b = await task
        except asyncio.CancelledError:
            proc = holder.get("proc")
            if proc is not None and proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 3.0)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(proc.wait)
            if not task.done():
                task.cancel()
                with contextlib.suppress(Exception):
                    await task
            duration = time.perf_counter() - start
            return ToolRunResult(
                status=RunStatus.CANCELLED,
                argv=tuple(inv.argv),
                exit_code=proc.returncode if proc is not None else None,
                duration_s=duration,
                command_cwd=cwd,
            )
        except Exception as exc:
            loop_name = _loop_debug_name()
            raise RuntimeError(
                "Async subprocess transport unavailable and fallback failed. "
                f"Running loop={loop_name!r}. On Windows, subprocess support requires a "
                "Proactor-capable loop."
            ) from exc

        for line in _decode_lines(out_b, encoding=inv.encoding, errors=inv.errors):
            if tee_out_f is not None:
                tee_out_f.write(line + "\n")
                tee_out_f.flush()
            await line_handlers[0](line)
        for line in _decode_lines(err_b, encoding=inv.encoding, errors=inv.errors):
            if tee_err_f is not None:
                tee_err_f.write(line + "\n")
                tee_err_f.flush()
            await line_handlers[1](line)

        duration = time.perf_counter() - start
        if timed_out:
            status = RunStatus.TIMED_OUT
        else:
            status = RunStatus.SUCCEEDED if exit_code == 0 else RunStatus.FAILED
        return ToolRunResult(
            status=status,
            argv=tuple(inv.argv),
            exit_code=exit_code,
            duration_s=duration,
            command_cwd=cwd,
        )


def _sync_run_awaitable(factory: Callable[[], Awaitable[T]]) -> T:
    """Run ``factory()`` to completion from synchronous code.

    Uses :func:`asyncio.run` when the current thread has no running loop. If a loop
    is already running (e.g. IPython/Jupyter or :mod:`pytest_asyncio`), the awaitable
    is executed in a worker thread with its own event loop so :func:`asyncio.run`
    is not nested on the same thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    def _in_thread() -> T:
        # Windows: new threads default to a selector loop without subprocess support;
        # Proactor is required for asyncio.create_subprocess_exec (IPython/Jupyter path).
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        return asyncio.run(factory())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_in_thread).result()


def run_sync(inv: SubprocessInvocation) -> ToolRunResult:
    """Blocking wrapper around :meth:`AsyncToolRunner.run`.

    Safe to call from sync scripts and from async contexts (e.g. notebooks) on the
    same thread: if a loop is already running, work runs in a helper thread.
    """
    return _sync_run_awaitable(lambda: AsyncToolRunner().run(inv))


def stream_events_sync(
    inv: SubprocessInvocation,
    *,
    parse_hook: Callable[[Any], AsyncIterator[Any]] | None = None,
) -> list[Any]:
    """Drain :meth:`AsyncToolRunner.stream_events` synchronously; returns all yielded events.

    This buffers the full event stream in memory. For large outputs, prefer the
    async API or process incrementally in async code.
    """
    async def _collect() -> list[Any]:
        return [e async for e in AsyncToolRunner().stream_events(inv, parse_hook=parse_hook)]

    return _sync_run_awaitable(_collect)


class SyncToolRunner:
    """Blocking façade mirroring :class:`AsyncToolRunner` for scripts and notebooks."""

    def run(self, inv: SubprocessInvocation) -> ToolRunResult:
        return run_sync(inv)

    def stream_events(
        self,
        inv: SubprocessInvocation,
        *,
        parse_hook: Callable[[Any], AsyncIterator[Any]] | None = None,
    ) -> list[Any]:
        return stream_events_sync(inv, parse_hook=parse_hook)