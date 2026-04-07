"""Fluent multi-stage pipeline: initial input via :func:`pipeline`, then :meth:`PipelineBuilder.run` / :meth:`PipelineBuilder.pipe`."""

from __future__ import annotations

import codecs
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyp9m4.parsers.common import ParseWarning
from pyp9m4.parsers.mace4 import Mace4Interpretation, Mace4InterpretationBuffer, parse_mace4_output
from pyp9m4.resolver import BinaryResolver, ToolName
from pyp9m4.prover9_facade import Prover9
from pyp9m4.runner import AsyncToolRunner, RunStatus, SubprocessInvocation, ToolRunResult
from pyp9m4.toolkit import (
    ToolRegistry,
    ToolRunEnvelope,
    _as_interpformat_options,
    _as_isofilter_options,
    _as_mace4_options,
    _as_prooftrans_options,
    _as_prover9_options,
    _tool_run_from_prover9,
    arun,
    normalize_tool_name,
)


def _coerce_initial_input(data: str | bytes | Path | None) -> str | bytes | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, Path):
        return data.read_bytes()
    return data


def _coerce_options_for(program: ToolName, options: Any) -> Any:
    if program == "prover9":
        return _as_prover9_options(options)
    if program == "mace4":
        return _as_mace4_options(options)
    if program == "isofilter":
        return _as_isofilter_options(options)
    if program == "interpformat":
        return _as_interpformat_options(options)
    if program == "prooftrans":
        return _as_prooftrans_options(options)
    return options


def _stderr_from_envelope(env: ToolRunEnvelope) -> str:
    if env.raw is not None:
        return env.raw.stderr
    if env.prover9 is not None:
        return env.prover9.stderr
    if env.pipeline is not None:
        return env.pipeline.stderr
    return ""


def _stdout_for_next(env: ToolRunEnvelope) -> str:
    if env.raw is not None:
        return env.raw.stdout
    if env.prover9 is not None:
        return env.prover9.stdout
    if env.pipeline is not None:
        return env.pipeline.stdout
    return ""


async def _arun_mace4_for_chain(
    registry: ToolRegistry,
    stdin: str | bytes | None,
    options: Any,
    **kwargs: Any,
) -> ToolRunEnvelope:
    """Run Mace4 once, capture stdout for chaining; optional isomorphic triple matches :class:`Mace4` semantics."""
    m4 = registry.mace4
    opts = _as_mace4_options(options)
    eff, timeout_s, elim = m4._effective_options(options=opts, kwargs=dict(kwargs))

    if elim:
        st, code, out, err, interps = await m4._arun_isomorphic_pipeline(
            stdin,
            eff,
            timeout_s=timeout_s,
        )
        raw = ToolRunResult(
            status=st,
            argv=(),
            exit_code=code,
            duration_s=0.0,
            stdout=out,
            stderr=err,
        )
        return ToolRunEnvelope(program="mace4", raw=raw, mace4_models=interps)

    inv = m4._build_inv(eff, stdin=stdin, timeout_s=timeout_s)
    res = await AsyncToolRunner().run(inv)
    models = parse_mace4_output(res.stdout).interpretations
    return ToolRunEnvelope(program="mace4", raw=res, mace4_models=tuple(models))


async def _run_one(
    program: ToolName,
    stdin: str | bytes | None,
    registry: ToolRegistry,
    options: Any,
    **kwargs: Any,
) -> ToolRunEnvelope:
    if program == "mace4":
        return await _arun_mace4_for_chain(registry, stdin, options, **kwargs)
    opts = _coerce_options_for(program, options)
    return await arun(program, stdin, options=opts, registry=registry, **kwargs)


def _invs_for_step(
    registry: ToolRegistry,
    program: ToolName,
    options: Any,
    merged: dict[str, Any],
) -> list[SubprocessInvocation]:
    """Build subprocess invocations for one user pipeline stage (may expand mace4+elim to three)."""
    if program == "mace4":
        m4 = registry.mace4
        opts = _as_mace4_options(options)
        eff, timeout_s, elim = m4._effective_options(options=opts, kwargs=dict(merged))
        if elim:
            ifc = registry.interpformat
            iso = registry.isofilter
            return [
                m4._build_inv(eff, stdin=None, timeout_s=timeout_s),
                ifc._build_inv(m4._ifc_default, stdin=None, timeout_s=timeout_s),
                iso._build_inv(m4._iso_default, stdin=None, timeout_s=timeout_s),
            ]
        return [m4._build_inv(eff, stdin=None, timeout_s=timeout_s)]
    if program == "isofilter":
        iso = registry.isofilter
        o, timeout_s = iso._effective_options(options=_as_isofilter_options(options), kwargs=dict(merged))
        return [iso._build_inv(o, stdin=None, timeout_s=timeout_s)]
    if program == "interpformat":
        ifc = registry.interpformat
        o, timeout_s = ifc._effective_options(options=_as_interpformat_options(options), kwargs=dict(merged))
        return [ifc._build_inv(o, stdin=None, timeout_s=timeout_s)]
    if program == "prooftrans":
        pt = registry.prooftrans
        o, timeout_s = pt._effective_options(options=_as_prooftrans_options(options), kwargs=dict(merged))
        return [pt._build_inv(o, stdin=None, timeout_s=timeout_s)]
    if program == "prover9":
        p9 = registry.prover9
        o, timeout_s = p9._effective_options(options=_as_prover9_options(options), kwargs=dict(merged))
        return [p9._build_inv(o, stdin=None, timeout_s=timeout_s)]
    raise ValueError(f"pipeline streaming does not support program {program!r}")


def _flatten_invs(
    registry: ToolRegistry,
    steps: list[tuple[ToolName, Any, dict[str, Any]]],
    merged_defaults: dict[str, Any],
) -> tuple[list[SubprocessInvocation], list[tuple[int, int]]]:
    flat: list[SubprocessInvocation] = []
    ranges: list[tuple[int, int]] = []
    for program, options, kw in steps:
        merged = {**merged_defaults, **kw}
        start = len(flat)
        flat.extend(_invs_for_step(registry, program, options, merged))
        ranges.append((start, len(flat)))
    return flat, ranges


def _pipeline_can_stream(steps: list[tuple[ToolName, Any, dict[str, Any]]]) -> bool:
    for program, _, _ in steps:
        if program == "clausetester":
            return False
    return True


async def _maybe_await(x: object) -> None:
    if inspect.isawaitable(x):
        await x


def _mace4_chunk_handler(
    encoding: str,
    errors: str,
    on_model: Callable[[Mace4Interpretation, tuple[ParseWarning, ...]], object],
) -> Callable[[bytes], Awaitable[None]]:
    buf = Mace4InterpretationBuffer()
    dec = codecs.getincrementaldecoder(encoding)(errors)

    async def cb(chunk: bytes) -> None:
        if chunk == b"":
            tail = dec.decode(b"", final=True)
            if tail:
                for mi, w in buf.feed(tail):
                    await _maybe_await(on_model(mi, w))
            return
        text = dec.decode(chunk)
        for mi, w in buf.feed(text):
            await _maybe_await(on_model(mi, w))

    return cb


def _envelope_for_user_step(
    registry: ToolRegistry,
    program: ToolName,
    *,
    stdout: str,
    stderr: str,
    status: RunStatus,
    exit_code: int | None,
    mace4_models: tuple[Mace4Interpretation, ...] | None,
) -> ToolRunEnvelope:
    raw = ToolRunResult(
        status=status,
        argv=(),
        exit_code=exit_code,
        duration_s=0.0,
        stdout=stdout,
        stderr=stderr,
    )
    if program == "mace4":
        return ToolRunEnvelope(program="mace4", raw=raw, mace4_models=mace4_models)
    if program == "prover9":
        p9: Prover9 = registry.prover9
        pr = p9._proof_result_from_run(raw)
        exe = registry.resolver.resolve("prover9")
        raw2 = _tool_run_from_prover9(pr, prover9_exe=exe)
        return ToolRunEnvelope(program="prover9", raw=raw2, prover9=pr)
    return ToolRunEnvelope(program=program, raw=raw)


@dataclass(frozen=True, slots=True)
class ChainStep:
    """One executed stage: tool name and the :class:`ToolRunEnvelope` from that run."""

    program: ToolName
    envelope: ToolRunEnvelope

    def to_dict(self) -> dict[str, Any]:
        return {"program": self.program, "envelope": self.envelope.to_dict()}


@dataclass(frozen=True, slots=True)
class ChainResult:
    """Outcome of :meth:`PipelineBuilder.execute`: each step’s envelope plus final stdout/stderr."""

    steps: tuple[ChainStep, ...]
    final_stdout: str
    final_stderr: str
    stream_intermediate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "final_stdout": self.final_stdout,
            "final_stderr": self.final_stderr,
            "stream_intermediate": self.stream_intermediate,
        }


class PipelineBuilder:
    """Build a linear chain: one :meth:`run` with the initial input, then :meth:`pipe` stages using prior stdout."""

    __slots__ = ("_initial", "_registry", "_steps", "_default_stage_kw")

    def __init__(
        self,
        initial: str | bytes | Path | None,
        *,
        registry: ToolRegistry | None = None,
        resolver: BinaryResolver | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._initial = initial
        self._registry = registry or ToolRegistry(resolver=resolver)
        self._steps: list[tuple[ToolName, Any, dict[str, Any]]] = []
        kw: dict[str, Any] = {}
        if cwd is not None:
            kw["cwd"] = cwd
        if env is not None:
            kw["env"] = dict(env)
        if timeout_s is not None:
            kw["timeout_s"] = timeout_s
        self._default_stage_kw = kw

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def run(
        self,
        program: ToolName | str,
        options: Any = None,
        **kwargs: Any,
    ) -> PipelineBuilder:
        if self._steps:
            raise ValueError(
                "PipelineBuilder.run() may only be used once at the start of the chain; "
                "use .pipe() for subsequent stages."
            )
        name = normalize_tool_name(str(program))
        self._steps.append((name, options, dict(kwargs)))
        return self

    def pipe(
        self,
        program: ToolName | str,
        options: Any = None,
        **kwargs: Any,
    ) -> PipelineBuilder:
        if not self._steps:
            raise ValueError("PipelineBuilder: call .run() first with the first tool and initial input.")
        name = normalize_tool_name(str(program))
        self._steps.append((name, options, dict(kwargs)))
        return self

    async def execute(
        self,
        *,
        stream_intermediate: bool = True,
        buffer_last_stdout: bool = True,
        last_stdout_path: Path | str | None = None,
        on_last_stdout_line: Callable[[str], Awaitable[None] | None] | None = None,
        on_last_stdout_chunk: Callable[[bytes], Awaitable[None] | None] | None = None,
        on_last_mace4_interpretation: Callable[
            [Mace4Interpretation, tuple[ParseWarning, ...]], Awaitable[None] | None
        ]
        | None = None,
    ) -> ChainResult:
        """Run the pipeline.

        By default, data is streamed between subprocesses (64 KiB pumps) so intermediate stages
        do not buffer full stdout in memory.

        For large final output, set ``buffer_last_stdout=False`` and use ``last_stdout_path``,
        ``on_last_stdout_line``, ``on_last_stdout_chunk``, or ``on_last_mace4_interpretation``
        to consume the last stage incrementally.

        Set ``stream_intermediate=False`` to restore the previous behaviour (full stdout buffered
        between each user stage).
        """
        if not self._steps:
            raise ValueError("PipelineBuilder: add at least one stage with .run().")

        if on_last_mace4_interpretation is not None and on_last_stdout_chunk is not None:
            raise ValueError("use only one of on_last_mace4_interpretation or on_last_stdout_chunk")

        if stream_intermediate and _pipeline_can_stream(self._steps):
            return await self._execute_streaming(
                buffer_last_stdout=buffer_last_stdout,
                last_stdout_path=last_stdout_path,
                on_last_stdout_line=on_last_stdout_line,
                on_last_stdout_chunk=on_last_stdout_chunk,
                on_last_mace4_interpretation=on_last_mace4_interpretation,
            )

        current: str | bytes | None = _coerce_initial_input(self._initial)
        out_steps: list[ChainStep] = []

        for program, options, kw in self._steps:
            merged = {**self._default_stage_kw, **kw}
            env = await _run_one(program, current, self._registry, options, **merged)
            out_steps.append(ChainStep(program=program, envelope=env))
            current = _stdout_for_next(env)

        last = out_steps[-1].envelope
        return ChainResult(
            steps=tuple(out_steps),
            final_stdout=_stdout_for_next(last),
            final_stderr=_stderr_from_envelope(last),
            stream_intermediate=False,
        )

    async def _execute_streaming(
        self,
        *,
        buffer_last_stdout: bool,
        last_stdout_path: Path | str | None,
        on_last_stdout_line: Callable[[str], Awaitable[None] | None] | None,
        on_last_stdout_chunk: Callable[[bytes], Awaitable[None] | None] | None,
        on_last_mace4_interpretation: Callable[
            [Mace4Interpretation, tuple[ParseWarning, ...]], Awaitable[None] | None
        ]
        | None,
    ) -> ChainResult:
        merged_defaults = dict(self._default_stage_kw)
        flat_invs, ranges = _flatten_invs(self._registry, self._steps, merged_defaults)
        encoding = flat_invs[0].encoding if flat_invs else "utf-8"
        errors = flat_invs[0].errors if flat_invs else "replace"

        chunk_cb = on_last_stdout_chunk
        if on_last_mace4_interpretation is not None:
            chunk_cb = _mace4_chunk_handler(encoding, errors, on_last_mace4_interpretation)

        eff_timeout = merged_defaults.get("timeout_s")

        st, code, last_out, last_err, per_inv_err = await AsyncToolRunner().run_pipe_chain(
            flat_invs,
            initial_stdin=_coerce_initial_input(self._initial),
            timeout_s=eff_timeout,
            accumulate_last_stdout=buffer_last_stdout,
            on_last_stdout_line=on_last_stdout_line,
            last_stdout_path=last_stdout_path,
            on_last_stdout_chunk=chunk_cb,
        )

        out_steps: list[ChainStep] = []

        for j, (program, _options, kw) in enumerate(self._steps):
            start, end = ranges[j]
            err_seg = "\n".join(per_inv_err[start:end])
            is_last = j == len(self._steps) - 1
            stdout_seg = last_out if is_last else ""
            models: tuple[Mace4Interpretation, ...] | None = None
            if is_last and program == "mace4" and buffer_last_stdout and last_out.strip():
                models = tuple(parse_mace4_output(last_out).interpretations)

            env = _envelope_for_user_step(
                self._registry,
                program,
                stdout=stdout_seg,
                stderr=err_seg,
                status=st,
                exit_code=code,
                mace4_models=models,
            )
            out_steps.append(ChainStep(program=program, envelope=env))

        return ChainResult(
            steps=tuple(out_steps),
            final_stdout=last_out,
            final_stderr=last_err,
            stream_intermediate=True,
        )


def pipeline(
    input: str | bytes | Path | None = None,
    *,
    resolver: BinaryResolver | None = None,
    registry: ToolRegistry | None = None,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float | None = None,
) -> PipelineBuilder:
    """Start a pipeline with optional stdin for the first :meth:`~PipelineBuilder.run` stage."""
    return PipelineBuilder(
        input,
        registry=registry,
        resolver=resolver,
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
    )
