"""Fluent multi-stage pipeline: initial input via :func:`pipeline`, then :meth:`PipelineBuilder.run` / :meth:`PipelineBuilder.pipe`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyp9m4.parsers.mace4 import parse_mace4_output
from pyp9m4.resolver import BinaryResolver, ToolName
from pyp9m4.runner import AsyncToolRunner, ToolRunResult
from pyp9m4.toolkit import (
    ToolRegistry,
    ToolRunEnvelope,
    _as_interpformat_options,
    _as_isofilter_options,
    _as_mace4_options,
    _as_prooftrans_options,
    _as_prover9_options,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "final_stdout": self.final_stdout,
            "final_stderr": self.final_stderr,
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

    async def execute(self) -> ChainResult:
        if not self._steps:
            raise ValueError("PipelineBuilder: add at least one stage with .run().")

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
