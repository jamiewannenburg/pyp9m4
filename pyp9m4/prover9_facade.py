"""High-level :class:`Prover9` facade: constructor defaults, merged call overrides, async jobs."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from pyp9m4.jobs import JobLifecycle, Prover9JobStatusSnapshot
from pyp9m4.options.prover9 import Prover9CliOptions
from pyp9m4.parsers.prover9 import Prover9Parsed, parse_prover9_output
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import (
    AsyncToolRunner,
    RunStatus,
    SubprocessInvocation,
    ToolRunResult,
    _sync_run_awaitable,
)

_PROVER9_FIELD_NAMES: frozenset[str] = frozenset(f.name for f in fields(Prover9CliOptions))
_FACADE_KW: frozenset[str] = frozenset({"timeout_s"})


def _run_status_to_lifecycle(status: RunStatus) -> JobLifecycle:
    return status.value  # type: ignore[return-value]


def _stderr_tail(text: str, *, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _split_prover9_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    p9_part: dict[str, Any] = {}
    facade_part: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in _FACADE_KW:
            facade_part[k] = v
        elif k in _PROVER9_FIELD_NAMES:
            p9_part[k] = v
        else:
            raise TypeError(f"Prover9: unexpected keyword argument {k!r}")
    return p9_part, facade_part


def _coerce_stdin(data: str | bytes | Path | None) -> str | bytes | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, Path):
        return data.read_bytes()
    return data


@dataclass(frozen=True, slots=True)
class Prover9ProofResult:
    """Outcome of :meth:`Prover9.run` / :meth:`Prover9.arun` / :meth:`Prover9ProofHandle.result`.

    :attr:`parsed` is the main value; :attr:`stdout` and :attr:`stderr` are attached for debugging.
    """

    parsed: Prover9Parsed
    stdout: str
    stderr: str
    exit_code: int | None
    lifecycle: JobLifecycle


@dataclass
class _Prover9JobState:
    lifecycle: JobLifecycle = "pending"
    exit_code: int | None = None
    stderr_lines: list[str] = field(default_factory=list)
    argv: tuple[str, ...] = ()
    result: Prover9ProofResult | None = None

    def snapshot(self) -> Prover9JobStatusSnapshot:
        tail = _stderr_tail("\n".join(self.stderr_lines))
        return Prover9JobStatusSnapshot(
            lifecycle=self.lifecycle,
            exit_code=self.exit_code,
            stderr_tail=tail,
            argv=self.argv,
        )


class Prover9ProofHandle:
    """Background Prover9 run; poll with :meth:`status` on the same event loop that started it."""

    __slots__ = ("_result_event", "_runner_task", "_state")

    def __init__(
        self,
        *,
        runner_task: asyncio.Task[None],
        state: _Prover9JobState,
        result_event: asyncio.Event,
    ) -> None:
        self._runner_task = runner_task
        self._state = state
        self._result_event = result_event

    @property
    def argv(self) -> tuple[str, ...]:
        return self._state.argv

    async def status(self) -> Prover9JobStatusSnapshot:
        return self._state.snapshot()

    async def wait(self) -> None:
        await self._result_event.wait()

    async def result(self) -> Prover9ProofResult:
        await self.wait()
        r = self._state.result
        if r is None:
            raise RuntimeError("Prover9 job finished without a result")
        return r

    def cancel(self) -> None:
        self._runner_task.cancel()


class Prover9:
    """Prover9 with constructor defaults and per-call merged overrides.

    **Precedence** (each call): call-time frequent kwargs beat ``options=`` (which replaces the
    instance baseline for that call). At construction, keyword arguments override the initial
    ``options=`` dataclass field-by-field.
    """

    __slots__ = (
        "_cwd",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_instance_options",
        "_prover9_path",
        "_resolver",
    )

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: Prover9CliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        prover9_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        p9_kw, fac_kw = _split_prover9_kwargs(dict(kwargs))
        self._resolver = resolver or BinaryResolver()
        self._prover9_path = Path(prover9_executable) if prover9_executable is not None else None
        base = options if options is not None else Prover9CliOptions()
        self._instance_options = replace(base, **p9_kw)
        self._default_timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    @property
    def default_options(self) -> Prover9CliOptions:
        """Effective Prover9 CLI options from the constructor (read-only)."""
        return self._instance_options

    def _exe_prover9(self) -> Path:
        return self._prover9_path or self._resolver.resolve("prover9")

    def _effective_options(
        self,
        *,
        options: Prover9CliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[Prover9CliOptions, float | None]:
        p9_kw, fac_kw = _split_prover9_kwargs(dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **p9_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _build_argv(self, opts: Prover9CliOptions) -> tuple[str, ...]:
        return (os.fspath(self._exe_prover9()), *opts.to_argv())

    def _build_inv(
        self,
        opts: Prover9CliOptions,
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return SubprocessInvocation(
            argv=self._build_argv(opts),
            cwd=self._cwd,
            env=self._env,
            stdin=stdin,
            timeout_s=timeout_s,
            encoding=self._encoding,
            errors=self._errors,
        )

    def _proof_result_from_run(self, res: ToolRunResult) -> Prover9ProofResult:
        life = _run_status_to_lifecycle(res.status)
        parsed = parse_prover9_output(res.stdout)
        return Prover9ProofResult(
            parsed=parsed,
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.exit_code,
            lifecycle=life,
        )

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Prover9CliOptions | None = None,
        **kwargs: Any,
    ) -> Prover9ProofResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        return self._proof_result_from_run(res)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Prover9CliOptions | None = None,
        **kwargs: Any,
    ) -> Prover9ProofResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))

    def start_arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: Prover9CliOptions | None = None,
        **kwargs: Any,
    ) -> Prover9ProofHandle:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        argv = self._build_argv(opts)
        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        state = _Prover9JobState(argv=argv, lifecycle="pending")
        done_event = asyncio.Event()
        facade_self = self

        async def _run() -> None:
            state.lifecycle = "running"
            try:
                res = await AsyncToolRunner().run(inv)
                state.exit_code = res.exit_code
                state.stderr_lines.clear()
                state.stderr_lines.extend(res.stderr.splitlines())
                state.result = facade_self._proof_result_from_run(res)
                state.lifecycle = state.result.lifecycle
            except asyncio.CancelledError:
                state.lifecycle = "cancelled"
                if state.result is None:
                    tail = "\n".join(state.stderr_lines)
                    state.result = Prover9ProofResult(
                        parsed=parse_prover9_output(""),
                        stdout="",
                        stderr=tail,
                        exit_code=state.exit_code,
                        lifecycle="cancelled",
                    )
                # Completing normally lets :meth:`wait` / :meth:`result` observe cancellation.
            finally:
                done_event.set()

        task = asyncio.create_task(_run())
        return Prover9ProofHandle(runner_task=task, state=state, result_event=done_event)
