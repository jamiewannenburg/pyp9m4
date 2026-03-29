"""High-level :class:`Mace4` facade: defaults, streaming models, isomorphic filtering, async jobs."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from pyp9m4.jobs import JobLifecycle, Mace4JobStatusSnapshot
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.mace4 import Mace4CliOptions
from pyp9m4.parsers.common import ParseWarning
from pyp9m4.parsers.mace4 import Mace4Interpretation, Mace4InterpretationBuffer, parse_mace4_output
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import (
    AsyncToolRunner,
    RunStatus,
    StderrLine,
    StdoutLine,
    SubprocessInvocation,
    ToolRunResult,
    _sync_run_awaitable,
)

_MACE4_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in fields(Mace4CliOptions))
_FACADE_KW: frozenset[str] = frozenset({"timeout_s", "eliminate_isomorphic"})


def _run_status_to_lifecycle(status: RunStatus) -> JobLifecycle:
    return status.value  # type: ignore[return-value]


def _stderr_tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _split_mace4_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    mace4_part: dict[str, Any] = {}
    facade_part: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in _FACADE_KW:
            facade_part[k] = v
        elif k in _MACE4_FIELD_NAMES:
            mace4_part[k] = v
        else:
            raise TypeError(f"Mace4: unexpected keyword argument {k!r}")
    return mace4_part, facade_part


def _coerce_stdin(data: str | bytes | Path | None) -> str | bytes | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, Path):
        return data.read_bytes()
    return data


@dataclass
class _Mace4JobState:
    lifecycle: JobLifecycle = "pending"
    models_found: int = 0
    last_domain_size: int | None = None
    exit_code: int | None = None
    stderr_lines: list[str] = field(default_factory=list)
    argv: tuple[str, ...] = ()
    duration_s: float | None = None

    def snapshot(
        self,
        *,
        size_range: tuple[int | None, int | None] | None,
        domain_increment: int | None,
    ) -> Mace4JobStatusSnapshot:
        tail = _stderr_tail("\n".join(self.stderr_lines))
        return Mace4JobStatusSnapshot(
            lifecycle=self.lifecycle,
            models_found=self.models_found,
            last_domain_size=self.last_domain_size,
            current_size_range=size_range,
            exit_code=self.exit_code,
            stderr_tail=tail,
            argv=self.argv,
            domain_increment=domain_increment,
            duration_s=self.duration_s,
        )


class Mace4SearchHandle:
    """Background Mace4 search; poll with :meth:`status` on the same event loop that started it."""

    __slots__ = (
        "_argv",
        "_domain_increment",
        "_model_queue",
        "_result_event",
        "_runner_task",
        "_size_range",
        "_state",
    )

    def __init__(
        self,
        *,
        runner_task: asyncio.Task[None],
        state: _Mace4JobState,
        model_queue: asyncio.Queue[Mace4Interpretation | None],
        result_event: asyncio.Event,
        argv: tuple[str, ...],
        size_range: tuple[int | None, int | None] | None,
        domain_increment: int | None,
    ) -> None:
        self._runner_task = runner_task
        self._state = state
        self._model_queue = model_queue
        self._result_event = result_event
        self._argv = argv
        self._size_range = size_range
        self._domain_increment = domain_increment

    @property
    def argv(self) -> tuple[str, ...]:
        return self._argv

    async def status(self) -> Mace4JobStatusSnapshot:
        return self._state.snapshot(
            size_range=self._size_range,
            domain_increment=self._domain_increment,
        )

    async def wait(self) -> None:
        await self._result_event.wait()

    async def result(self) -> None:
        await self.wait()

    def cancel(self) -> None:
        self._runner_task.cancel()

    async def amodels(self) -> AsyncIterator[Mace4Interpretation]:
        while True:
            m = await self._model_queue.get()
            if m is None:
                break
            yield m


class Mace4:
    """Mace4 with constructor defaults and per-call merged overrides.

    **Precedence** (each call): call-time frequent kwargs beat ``options=`` (which replaces the
    instance baseline for that call). At construction, keyword arguments override the initial
    ``options=`` dataclass field-by-field.

    With ``eliminate_isomorphic=True``, runs ``mace4`` → ``interpformat`` → ``isofilter``; models
    are yielded only after the pipeline finishes (no cross-tool streaming).
    """

    __slots__ = (
        "_cwd",
        "_default_eliminate_iso",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_ifc_default",
        "_ifc_path",
        "_instance_options",
        "_iso_default",
        "_iso_path",
        "_mace4_path",
        "_resolver",
    )

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: Mace4CliOptions | None = None,
        interpformat_options: InterpformatCliOptions | None = None,
        isofilter_options: IsofilterCliOptions | None = None,
        eliminate_isomorphic: bool = False,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        mace4_executable: Path | str | None = None,
        interpformat_executable: Path | str | None = None,
        isofilter_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        m4_kw, fac_kw = _split_mace4_kwargs(dict(kwargs))
        self._resolver = resolver or BinaryResolver()
        self._mace4_path = Path(mace4_executable) if mace4_executable is not None else None
        self._ifc_path = Path(interpformat_executable) if interpformat_executable is not None else None
        self._iso_path = Path(isofilter_executable) if isofilter_executable is not None else None
        base = options if options is not None else Mace4CliOptions()
        self._instance_options = replace(base, **m4_kw)
        self._default_timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        self._default_eliminate_iso = (
            bool(fac_kw["eliminate_isomorphic"])
            if "eliminate_isomorphic" in fac_kw
            else eliminate_isomorphic
        )
        self._ifc_default = interpformat_options or InterpformatCliOptions(style="standard2")
        self._iso_default = isofilter_options or IsofilterCliOptions()
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    @property
    def default_options(self) -> Mace4CliOptions:
        """Effective Mace4 CLI options from the constructor (read-only)."""
        return self._instance_options

    def _exe_mace4(self) -> Path:
        return self._mace4_path or self._resolver.resolve("mace4")

    def _exe_interpformat(self) -> Path:
        return self._ifc_path or self._resolver.resolve("interpformat")

    def _exe_isofilter(self) -> Path:
        return self._iso_path or self._resolver.resolve("isofilter")

    def _effective_options(
        self,
        *,
        options: Mace4CliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[Mace4CliOptions, float | None, bool]:
        m4_kw, fac_kw = _split_mace4_kwargs(dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **m4_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        elim = (
            bool(fac_kw["eliminate_isomorphic"])
            if "eliminate_isomorphic" in fac_kw
            else self._default_eliminate_iso
        )
        return eff, timeout_s, elim

    def _size_range_hint(self, opts: Mace4CliOptions) -> tuple[int | None, int | None] | None:
        if opts.domain_size is None and opts.end_size is None:
            return None
        return (opts.domain_size, opts.end_size)

    def _build_argv(self, opts: Mace4CliOptions) -> tuple[str, ...]:
        return (os.fspath(self._exe_mace4()), *opts.to_argv())

    def _build_inv(
        self,
        opts: Mace4CliOptions,
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return SubprocessInvocation(
            argv=self._build_argv(opts),
            cwd=self._cwd,
            env=self._env,
            stdin=stdin if isinstance(stdin, str) else stdin,
            timeout_s=timeout_s,
            encoding=self._encoding,
            errors=self._errors,
        )

    async def _arun_isomorphic_pipeline(
        self,
        stdin: str | bytes | None,
        opts: Mace4CliOptions,
        *,
        timeout_s: float | None,
    ) -> tuple[RunStatus, int | None, str, str, tuple[Mace4Interpretation, ...]]:
        runner = AsyncToolRunner()
        inv_m = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        r1 = await runner.run(inv_m)
        if r1.status != RunStatus.SUCCEEDED:
            return r1.status, r1.exit_code, r1.stdout, r1.stderr, ()
        ifc = self._exe_interpformat()
        inv_i = SubprocessInvocation(
            argv=(os.fspath(ifc), *self._ifc_default.to_argv()),
            cwd=self._cwd,
            env=self._env,
            stdin=r1.stdout,
            timeout_s=timeout_s,
            encoding=self._encoding,
            errors=self._errors,
        )
        r2 = await runner.run(inv_i)
        if r2.status != RunStatus.SUCCEEDED:
            return r2.status, r2.exit_code, r2.stdout, r2.stderr, ()
        iso = self._exe_isofilter()
        inv_s = SubprocessInvocation(
            argv=(os.fspath(iso), *self._iso_default.to_argv()),
            cwd=self._cwd,
            env=self._env,
            stdin=r2.stdout,
            timeout_s=timeout_s,
            encoding=self._encoding,
            errors=self._errors,
        )
        r3 = await runner.run(inv_s)
        parsed = parse_mace4_output(r3.stdout)
        return r3.status, r3.exit_code, r3.stdout, r3.stderr, parsed.interpretations

    def _sync_isomorphic_pipeline(
        self,
        stdin: str | bytes | None,
        opts: Mace4CliOptions,
        *,
        timeout_s: float | None,
    ) -> tuple[RunStatus, int | None, str, str, tuple[Mace4Interpretation, ...]]:
        async def _go() -> tuple[RunStatus, int | None, str, str, tuple[Mace4Interpretation, ...]]:
            return await self._arun_isomorphic_pipeline(stdin, opts, timeout_s=timeout_s)

        return _sync_run_awaitable(_go)

    def models(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Mace4CliOptions | None = None,
        on_model: Callable[[Mace4Interpretation, tuple[ParseWarning, ...]], None] | None = None,
        **kwargs: Any,
    ) -> Iterator[Mace4Interpretation]:
        opts, timeout_s, elim = self._effective_options(options=options, kwargs=kwargs)
        stdin_raw = _coerce_stdin(input)
        stdin_bytes: bytes | None
        if stdin_raw is None:
            stdin_bytes = None
        elif isinstance(stdin_raw, bytes):
            stdin_bytes = stdin_raw
        else:
            stdin_bytes = stdin_raw.encode(self._encoding, errors=self._errors)

        if elim:
            st, _code, _out, _err, interps = self._sync_isomorphic_pipeline(
                stdin_raw,
                opts,
                timeout_s=timeout_s,
            )
            if st != RunStatus.SUCCEEDED:
                return
            for mi in interps:
                if on_model:
                    on_model(mi, ())
                yield mi
            return

        argv = list(self._build_argv(opts))
        proc: subprocess.Popen[bytes] | None = None
        err_lines: list[str] = []

        def pump_stderr(p: subprocess.Popen[bytes]) -> None:
            assert p.stderr is not None
            for raw in p.stderr:
                err_lines.append(raw.decode(self._encoding, errors=self._errors).rstrip("\r\n"))

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            t_err = threading.Thread(target=pump_stderr, args=(proc,), daemon=True)
            t_err.start()

            if stdin_bytes is not None:
                assert proc.stdin is not None
                proc.stdin.write(stdin_bytes)
            if proc.stdin is not None:
                proc.stdin.close()

            buf = Mace4InterpretationBuffer()
            assert proc.stdout is not None
            deadline = time.monotonic() + timeout_s if timeout_s is not None else None

            for raw_line in proc.stdout:
                if deadline is not None and time.monotonic() > deadline:
                    proc.terminate()
                    break
                line = raw_line.decode(self._encoding, errors=self._errors).rstrip("\r\n")
                for mi, warns in buf.feed(line + "\n"):
                    if on_model:
                        on_model(mi, warns)
                    yield mi

            proc.wait(timeout=5.0)
        finally:
            if proc is not None and proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=3.0)

    async def amodels(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Mace4CliOptions | None = None,
        on_model: Callable[[Mace4Interpretation, tuple[ParseWarning, ...]], Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Mace4Interpretation]:
        opts, timeout_s, elim = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        if isinstance(stdin, bytes):
            stdin = stdin.decode(self._encoding, errors=self._errors)

        if elim:
            st, _c, _o, _e, interps = await self._arun_isomorphic_pipeline(
                stdin,
                opts,
                timeout_s=timeout_s,
            )
            if st != RunStatus.SUCCEEDED:
                return
            for mi in interps:
                if on_model is not None:
                    r = on_model(mi, ())
                    if inspect.isawaitable(r):
                        await r
                yield mi
            return

        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        buf = Mace4InterpretationBuffer()
        runner = AsyncToolRunner()

        async def hook(e: Any) -> AsyncIterator[Any]:
            if isinstance(e, StdoutLine):
                for mi, warns in buf.feed(e.text + "\n"):
                    yield (mi, warns)

        async for ev in runner.stream_events(inv, parse_hook=hook):
            if isinstance(ev, tuple) and len(ev) == 2 and isinstance(ev[0], Mace4Interpretation):
                mi, warns = ev
                if on_model is not None:
                    r = on_model(mi, warns)
                    if inspect.isawaitable(r):
                        await r
                yield mi

    def start_amodels(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Mace4CliOptions | None = None,
        on_model: Callable[[Mace4Interpretation, tuple[ParseWarning, ...]], Any] | None = None,
        **kwargs: Any,
    ) -> Mace4SearchHandle:
        opts, timeout_s, elim = self._effective_options(options=options, kwargs=kwargs)
        stdin_raw = _coerce_stdin(input)
        if isinstance(stdin_raw, bytes):
            stdin_s = stdin_raw.decode(self._encoding, errors=self._errors)
        else:
            stdin_s = stdin_raw

        argv = self._build_argv(opts)
        size_range = self._size_range_hint(opts)
        state = _Mace4JobState(argv=argv, lifecycle="pending")
        queue: asyncio.Queue[Mace4Interpretation | None] = asyncio.Queue()
        done_event = asyncio.Event()
        mace4_self = self

        async def _run() -> None:
            t0 = time.perf_counter()
            state.lifecycle = "running"
            try:
                if elim:
                    st, code, _o, err, interps = await mace4_self._arun_isomorphic_pipeline(
                        stdin_s,
                        opts,
                        timeout_s=timeout_s,
                    )
                    state.exit_code = code
                    state.stderr_lines.clear()
                    state.stderr_lines.extend(err.splitlines())
                    state.lifecycle = _run_status_to_lifecycle(st)
                    for mi in interps:
                        state.models_found += 1
                        state.last_domain_size = mi.domain_size
                        if on_model is not None:
                            r = on_model(mi, ())
                            if inspect.isawaitable(r):
                                await r
                        await queue.put(mi)
                    return

                inv = mace4_self._build_inv(opts, stdin=stdin_s, timeout_s=timeout_s)
                buf = Mace4InterpretationBuffer()
                runner = AsyncToolRunner()

                async def hook(e: Any) -> AsyncIterator[Any]:
                    if isinstance(e, StdoutLine):
                        for mi, warns in buf.feed(e.text + "\n"):
                            yield (mi, warns)

                async def on_complete(res: ToolRunResult) -> None:
                    state.exit_code = res.exit_code
                    state.stderr_lines.clear()
                    state.stderr_lines.extend(res.stderr.splitlines())
                    state.lifecycle = _run_status_to_lifecycle(res.status)

                async for ev in runner.stream_events(inv, parse_hook=hook, on_complete=on_complete):
                    if isinstance(ev, tuple) and len(ev) == 2 and isinstance(ev[0], Mace4Interpretation):
                        mi, warns = ev
                        state.models_found += 1
                        state.last_domain_size = mi.domain_size
                        if on_model is not None:
                            r = on_model(mi, warns)
                            if inspect.isawaitable(r):
                                await r
                        await queue.put(mi)
            except asyncio.CancelledError:
                state.lifecycle = "cancelled"
                raise
            finally:
                state.duration_s = time.perf_counter() - t0
                await queue.put(None)
                done_event.set()

        task = asyncio.create_task(_run())
        return Mace4SearchHandle(
            runner_task=task,
            state=state,
            model_queue=queue,
            result_event=done_event,
            argv=argv,
            size_range=size_range,
            domain_increment=opts.increment,
        )
