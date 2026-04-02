"""Unified registry and :func:`arun` entry point for LADR tools (delegates to facades)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyp9m4.jobs import JobLifecycle
from pyp9m4.mace4_facade import Mace4
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.mace4 import Mace4CliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.options.prover9 import Prover9CliOptions
from pyp9m4.parsers.mace4 import Mace4Interpretation, parse_mace4_output
from pyp9m4.pipeline_facades import (
    Interpformat,
    Isofilter,
    PipelineToolResult,
    Prooftrans,
)
from pyp9m4.prover9_facade import Prover9, Prover9ProofResult
from pyp9m4.resolver import BinaryResolver, ToolName
from pyp9m4.runner import AsyncToolRunner, RunStatus, SubprocessInvocation, ToolRunResult
from pyp9m4.serialization import dataclass_to_json_dict

_TOOL_ALIASES: dict[str, ToolName] = {
    "if": "isofilter",
    "iso": "isofilter",
    "interp": "interpformat",
    "ifc": "interpformat",
    "modelformat": "interpformat",
    "pt": "prooftrans",
}

_PIPELINE_TOOL_NAMES: frozenset[ToolName] = frozenset(
    ("isofilter", "interpformat", "prooftrans")  # type: ignore[assignment]
)

_ALL_REGISTERED: frozenset[ToolName] = frozenset(
    ("prover9", "mace4", "isofilter", "interpformat", "prooftrans", "clausetester")  # type: ignore[assignment]
)


def normalize_tool_name(name: str) -> ToolName:
    """Normalize user input (case, common aliases) to a :data:`~pyp9m4.resolver.ToolName` literal."""
    n = name.strip().lower()
    n = _TOOL_ALIASES.get(n, n)
    if n not in (
        "prover9",
        "mace4",
        "interpformat",
        "isofilter",
        "prooftrans",
        "clausetester",
    ):
        raise ValueError(f"unknown tool name: {name!r}")
    return n  # type: ignore[return-value]


def _as_prover9_options(
    options: Prover9CliOptions | Mapping[str, Any] | None,
) -> Prover9CliOptions:
    if options is None:
        return Prover9CliOptions()
    if isinstance(options, Prover9CliOptions):
        return options
    if isinstance(options, Mapping):
        return Prover9CliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected Prover9CliOptions or mapping, got {type(options).__name__}")


def _as_mace4_options(
    options: Mace4CliOptions | Mapping[str, Any] | None,
) -> Mace4CliOptions:
    if options is None:
        return Mace4CliOptions()
    if isinstance(options, Mace4CliOptions):
        return options
    if isinstance(options, Mapping):
        return Mace4CliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected Mace4CliOptions or mapping, got {type(options).__name__}")


def _as_isofilter_options(
    options: IsofilterCliOptions | Mapping[str, Any] | None,
) -> IsofilterCliOptions:
    if options is None:
        return IsofilterCliOptions()
    if isinstance(options, IsofilterCliOptions):
        return options
    if isinstance(options, Mapping):
        return IsofilterCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected IsofilterCliOptions or mapping, got {type(options).__name__}")


def _as_interpformat_options(
    options: InterpformatCliOptions | Mapping[str, Any] | None,
) -> InterpformatCliOptions:
    if options is None:
        return InterpformatCliOptions()
    if isinstance(options, InterpformatCliOptions):
        return options
    if isinstance(options, Mapping):
        return InterpformatCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected InterpformatCliOptions or mapping, got {type(options).__name__}")


def _as_prooftrans_options(
    options: ProofTransCliOptions | Mapping[str, Any] | None,
) -> ProofTransCliOptions:
    if options is None:
        return ProofTransCliOptions()
    if isinstance(options, ProofTransCliOptions):
        return options
    if isinstance(options, Mapping):
        return ProofTransCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected ProofTransCliOptions or mapping, got {type(options).__name__}")


def _tool_run_from_prover9(
    pr: Prover9ProofResult,
    *,
    prover9_exe: Path,
) -> ToolRunResult:
    return ToolRunResult(
        status=RunStatus(pr.lifecycle),  # type: ignore[arg-type]
        argv=(str(prover9_exe),),
        exit_code=pr.exit_code,
        duration_s=0.0,
        stdout=pr.stdout,
        stderr=pr.stderr,
    )


@dataclass(frozen=True, slots=True)
class ToolRunEnvelope:
    """Tagged outcome of :func:`arun`: ``program``, optional subprocess :attr:`raw`, and typed payloads.

    Exactly one of ``prover9``, ``mace4_models``, or ``pipeline`` is typically set (besides
    ``raw``). For ``clausetester``, only :attr:`raw` is populated.
    """

    program: ToolName
    raw: ToolRunResult | None
    prover9: Prover9ProofResult | None = None
    mace4_models: tuple[Mace4Interpretation, ...] | None = None
    pipeline: PipelineToolResult | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly dict (omit unset typed payloads; include :attr:`raw` when present)."""
        out: dict[str, Any] = {"program": self.program}
        if self.raw is not None:
            out["raw"] = self.raw.to_dict()
        if self.prover9 is not None:
            out["prover9"] = self.prover9.to_dict()
        if self.mace4_models is not None:
            out["mace4_models"] = [dataclass_to_json_dict(m) for m in self.mace4_models]
        if self.pipeline is not None:
            out["pipeline"] = self.pipeline.to_dict()
        return out


class ToolRegistry:
    """Maps tool names to facade instances (plus resolver); use :meth:`get` or :func:`arun`."""

    __slots__ = ("_interpformat", "_isofilter", "_mace4", "_prooftrans", "_prover9", "_resolver")

    def __init__(self, *, resolver: BinaryResolver | None = None) -> None:
        self._resolver = resolver or BinaryResolver()
        self._prover9 = Prover9(resolver=self._resolver)
        self._mace4 = Mace4(resolver=self._resolver)
        self._isofilter = Isofilter(resolver=self._resolver)
        self._interpformat = Interpformat(resolver=self._resolver)
        self._prooftrans = Prooftrans(resolver=self._resolver)

    @property
    def resolver(self) -> BinaryResolver:
        return self._resolver

    @property
    def prover9(self) -> Prover9:
        return self._prover9

    @property
    def mace4(self) -> Mace4:
        return self._mace4

    @property
    def isofilter(self) -> Isofilter:
        return self._isofilter

    @property
    def interpformat(self) -> Interpformat:
        return self._interpformat

    @property
    def prooftrans(self) -> Prooftrans:
        return self._prooftrans

    def get(
        self, program: ToolName | str
    ) -> Prover9 | Mace4 | Isofilter | Interpformat | Prooftrans:
        """Return the facade for a supported tool (not ``clausetester``, which has no facade)."""
        name = normalize_tool_name(str(program))
        if name == "prover9":
            return self._prover9
        if name == "mace4":
            return self._mace4
        if name == "isofilter":
            return self._isofilter
        if name == "interpformat":
            return self._interpformat
        if name == "prooftrans":
            return self._prooftrans
        raise KeyError(
            f"no facade object for {name!r} (clausetester has no high-level facade; use "
            "arun(..., interp_file=...) or SubprocessInvocation)"
        )

    def registered_tool_names(self) -> frozenset[ToolName]:
        """All tool names dispatchable via :func:`arun`."""
        return _ALL_REGISTERED

    def registered_pipeline_tools(self) -> frozenset[ToolName]:
        """Subset with first-class pipeline facades (``isofilter``, ``interpformat``, ``prooftrans``)."""
        return _PIPELINE_TOOL_NAMES


async def arun(
    program: ToolName | str,
    input: str | bytes | Path | None = None,
    *,
    options: Prover9CliOptions
    | Mace4CliOptions
    | IsofilterCliOptions
    | InterpformatCliOptions
    | ProofTransCliOptions
    | Mapping[str, Any]
    | None = None,
    resolver: BinaryResolver | None = None,
    registry: ToolRegistry | None = None,
    **kwargs: Any,
) -> ToolRunEnvelope:
    """Run a named LADR tool to completion and return a :class:`ToolRunEnvelope`.

    Dispatches to :class:`~pyp9m4.prover9_facade.Prover9`, :class:`~pyp9m4.mace4_facade.Mace4`,
    or pipeline facades. For ``mace4``, this collects all models (same semantics as exhausting
    :meth:`~pyp9m4.mace4_facade.Mace4.amodels`); streaming stays on ``amodels`` / handles.

    For ``clausetester``, pass ``interp_file=`` (path to an interpretations file); ``input`` is
    sent on stdin (clause stream).
    """
    reg = registry or ToolRegistry(resolver=resolver)
    name = normalize_tool_name(str(program))

    if name == "prover9":
        opts = _as_prover9_options(options)
        pr = await reg.prover9.arun(input, options=opts, **kwargs)
        exe = reg.resolver.resolve("prover9")
        raw = _tool_run_from_prover9(pr, prover9_exe=exe)
        return ToolRunEnvelope(program="prover9", raw=raw, prover9=pr)

    if name == "mace4":
        opts = _as_mace4_options(options)
        m4 = reg.mace4
        eff, timeout_s, elim = m4._effective_options(options=opts, kwargs=dict(kwargs))
        stdin = input
        if isinstance(stdin, Path):
            stdin = stdin.read_bytes()
        if isinstance(stdin, bytes):
            stdin = stdin.decode(m4._encoding, errors=m4._errors)

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

    if name == "isofilter":
        opts = _as_isofilter_options(options)
        pipe = await reg.isofilter.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="isofilter", raw=raw, pipeline=pipe)

    if name == "interpformat":
        opts = _as_interpformat_options(options)
        pipe = await reg.interpformat.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="interpformat", raw=raw, pipeline=pipe)

    if name == "prooftrans":
        opts = _as_prooftrans_options(options)
        pipe = await reg.prooftrans.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="prooftrans", raw=raw, pipeline=pipe)

    if name == "clausetester":
        interp_file = kwargs.pop("interp_file", None)
        if interp_file is None:
            raise ValueError("clausetester requires keyword-only interp_file= (path to interpretations file)")
        timeout_s = kwargs.pop("timeout_s", None)
        cwd = kwargs.pop("cwd", None)
        env = kwargs.pop("env", None)
        encoding = kwargs.pop("encoding", "utf-8")
        errors = kwargs.pop("errors", "replace")
        if kwargs:
            bad = next(iter(kwargs))
            raise TypeError(f"arun(clausetester): unexpected keyword argument {bad!r}")

        exe = reg.resolver.resolve("clausetester")
        inv = SubprocessInvocation(
            argv=(str(exe), os.fspath(interp_file)),
            cwd=cwd,
            env=env,
            stdin=input,
            timeout_s=timeout_s,
            encoding=encoding,
            errors=errors,
        )
        res = await AsyncToolRunner().run(inv)
        return ToolRunEnvelope(program="clausetester", raw=res)

    raise AssertionError(f"unhandled tool: {name!r}")


def _pipeline_to_tool_run(pipe: PipelineToolResult) -> ToolRunResult:
    life: JobLifecycle = pipe.lifecycle
    return ToolRunResult(
        status=RunStatus(life),  # type: ignore[arg-type]
        argv=(),
        exit_code=pipe.exit_code,
        duration_s=0.0,
        stdout=pipe.stdout,
        stderr=pipe.stderr,
    )
