"""First-class facades for LADR pipeline tools: ``isofilter``, ``interpformat``, ``prooftrans``."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from pyp9m4.jobs import JobLifecycle
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.parsers.pipeline import (
    PipelineTextInspection,
    PipelineTextResult,
    inspect_pipeline_text,
    parse_pipeline_tool_output,
)
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import AsyncToolRunner, RunStatus, SubprocessInvocation, ToolRunResult, _sync_run_awaitable
from pyp9m4.serialization import dataclass_to_json_dict

_FACADE_KW: frozenset[str] = frozenset({"timeout_s"})

_ISO_FIELDS: frozenset[str] = frozenset(f.name for f in fields(IsofilterCliOptions))
_IFC_FIELDS: frozenset[str] = frozenset(f.name for f in fields(InterpformatCliOptions))
_PT_FIELDS: frozenset[str] = frozenset(f.name for f in fields(ProofTransCliOptions))


def _run_status_to_lifecycle(status: RunStatus) -> JobLifecycle:
    return status.value  # type: ignore[return-value]


def _split_kwargs(
    field_names: frozenset[str],
    facade_name: str,
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    opt_part: dict[str, Any] = {}
    fac_part: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in _FACADE_KW:
            fac_part[k] = v
        elif k in field_names:
            opt_part[k] = v
        else:
            raise TypeError(f"{facade_name}: unexpected keyword argument {k!r}")
    return opt_part, fac_part


def _coerce_stdin(data: str | bytes | Path | None) -> str | bytes | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        return data
    if isinstance(data, Path):
        return data.read_bytes()
    return data


def _pipeline_result_from_run(res: ToolRunResult) -> PipelineToolResult:
    life = _run_status_to_lifecycle(res.status)
    wrapped = parse_pipeline_tool_output(res.stdout, res.stderr)
    insp = inspect_pipeline_text(res.stdout, res.stderr)
    return PipelineToolResult(
        stdout=res.stdout,
        stderr=res.stderr,
        exit_code=res.exit_code,
        lifecycle=life,
        text=wrapped,
        inspection=insp,
    )


@dataclass(frozen=True, slots=True)
class PipelineToolResult:
    """Structured outcome of :meth:`Isofilter.arun` / :meth:`Interpformat.arun` / :meth:`Prooftrans.arun`.

    :attr:`text` mirrors :func:`~pyp9m4.parsers.parse_pipeline_tool_output`; :attr:`inspection`
    adds :func:`~pyp9m4.parsers.inspect_pipeline_text` heuristics for logging or APIs.
    """

    stdout: str
    stderr: str
    exit_code: int | None
    lifecycle: JobLifecycle
    text: PipelineTextResult
    inspection: PipelineTextInspection

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly result (nested dataclasses, tuples as lists)."""
        return dataclass_to_json_dict(self)


class Isofilter:
    """``isofilter`` with constructor defaults, merged call overrides, and parsed text bundles."""

    __slots__ = (
        "_cwd",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_instance_options",
        "_isofilter_path",
        "_resolver",
    )

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: IsofilterCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        isofilter_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        iso_kw, fac_kw = _split_kwargs(_ISO_FIELDS, "Isofilter", dict(kwargs))
        self._resolver = resolver or BinaryResolver()
        self._isofilter_path = Path(isofilter_executable) if isofilter_executable is not None else None
        base = options if options is not None else IsofilterCliOptions()
        self._instance_options = replace(base, **iso_kw)
        self._default_timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    @property
    def default_options(self) -> IsofilterCliOptions:
        return self._instance_options

    def _exe(self) -> Path:
        return self._isofilter_path or self._resolver.resolve("isofilter")

    def _effective_options(
        self,
        *,
        options: IsofilterCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[IsofilterCliOptions, float | None]:
        iso_kw, fac_kw = _split_kwargs(_ISO_FIELDS, "Isofilter", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **iso_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _build_argv(self, opts: IsofilterCliOptions) -> tuple[str, ...]:
        return (os.fspath(self._exe()), *opts.to_argv())

    def _build_inv(
        self,
        opts: IsofilterCliOptions,
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

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: IsofilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        return _pipeline_result_from_run(res)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: IsofilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class Interpformat:
    """``interpformat`` (``modelformat``) with defaults, merged overrides, and parsed text bundles."""

    __slots__ = (
        "_cwd",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_instance_options",
        "_interpformat_path",
        "_resolver",
    )

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: InterpformatCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        interpformat_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        ifc_kw, fac_kw = _split_kwargs(_IFC_FIELDS, "Interpformat", dict(kwargs))
        self._resolver = resolver or BinaryResolver()
        self._interpformat_path = Path(interpformat_executable) if interpformat_executable is not None else None
        base = options if options is not None else InterpformatCliOptions()
        self._instance_options = replace(base, **ifc_kw)
        self._default_timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    @property
    def default_options(self) -> InterpformatCliOptions:
        return self._instance_options

    def _exe(self) -> Path:
        return self._interpformat_path or self._resolver.resolve("interpformat")

    def _effective_options(
        self,
        *,
        options: InterpformatCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[InterpformatCliOptions, float | None]:
        ifc_kw, fac_kw = _split_kwargs(_IFC_FIELDS, "Interpformat", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **ifc_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _build_argv(self, opts: InterpformatCliOptions) -> tuple[str, ...]:
        return (os.fspath(self._exe()), *opts.to_argv())

    def _build_inv(
        self,
        opts: InterpformatCliOptions,
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

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: InterpformatCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        return _pipeline_result_from_run(res)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: InterpformatCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class Prooftrans:
    """``prooftrans`` with defaults, merged overrides, and parsed text bundles."""

    __slots__ = (
        "_cwd",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_instance_options",
        "_prooftrans_path",
        "_resolver",
    )

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: ProofTransCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        prooftrans_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        pt_kw, fac_kw = _split_kwargs(_PT_FIELDS, "Prooftrans", dict(kwargs))
        self._resolver = resolver or BinaryResolver()
        self._prooftrans_path = Path(prooftrans_executable) if prooftrans_executable is not None else None
        base = options if options is not None else ProofTransCliOptions()
        self._instance_options = replace(base, **pt_kw)
        self._default_timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    @property
    def default_options(self) -> ProofTransCliOptions:
        return self._instance_options

    def _exe(self) -> Path:
        return self._prooftrans_path or self._resolver.resolve("prooftrans")

    def _effective_options(
        self,
        *,
        options: ProofTransCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[ProofTransCliOptions, float | None]:
        pt_kw, fac_kw = _split_kwargs(_PT_FIELDS, "Prooftrans", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **pt_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _build_argv(self, opts: ProofTransCliOptions) -> tuple[str, ...]:
        return (os.fspath(self._exe()), *opts.to_argv())

    def _build_inv(
        self,
        opts: ProofTransCliOptions,
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

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: ProofTransCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        inv = self._build_inv(opts, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        return _pipeline_result_from_run(res)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: ProofTransCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))
