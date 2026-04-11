"""First-class facades for LADR pipeline tools (shared subprocess base + per-binary classes)."""

from __future__ import annotations

import os
from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, ClassVar

from pyp9m4.jobs import JobLifecycle
from pyp9m4.options.clausefilter import ClausefilterCliOptions
from pyp9m4.options.clausetester import ClausetesterCliOptions
from pyp9m4.options.interpfilter import InterpfilterCliOptions
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.ladr_to_tptp import LadrToTptpCliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.options.renamer import RenamerCliOptions
from pyp9m4.options.rewriter import RewriterCliOptions
from pyp9m4.options.test_clause_eval import TestClauseEvalCliOptions
from pyp9m4.options.tptp_to_ladr import TptpToLadrCliOptions
from pyp9m4.parsers.pipeline import (
    PipelineTextInspection,
    PipelineTextResult,
    inspect_pipeline_text,
    parse_pipeline_tool_output,
)
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import AsyncToolRunner, RunStatus, SubprocessInvocation, ToolRunResult, _sync_run_awaitable

_FACADE_KW: frozenset[str] = frozenset({"timeout_s"})

_ISO_FIELDS: frozenset[str] = frozenset(f.name for f in fields(IsofilterCliOptions))
_IFC_FIELDS: frozenset[str] = frozenset(f.name for f in fields(InterpformatCliOptions))
_PT_FIELDS: frozenset[str] = frozenset(f.name for f in fields(ProofTransCliOptions))
_IFL_FIELDS: frozenset[str] = frozenset(f.name for f in fields(InterpfilterCliOptions))
_CLF_FIELDS: frozenset[str] = frozenset(f.name for f in fields(ClausefilterCliOptions))
_RW_FIELDS: frozenset[str] = frozenset(f.name for f in fields(RewriterCliOptions))
_T2L_FIELDS: frozenset[str] = frozenset(f.name for f in fields(TptpToLadrCliOptions))
_L2T_FIELDS: frozenset[str] = frozenset(f.name for f in fields(LadrToTptpCliOptions))
_RN_FIELDS: frozenset[str] = frozenset(f.name for f in fields(RenamerCliOptions))
_TCE_FIELDS: frozenset[str] = frozenset(f.name for f in fields(TestClauseEvalCliOptions))
_CT_FIELDS: frozenset[str] = frozenset(f.name for f in fields(ClausetesterCliOptions))


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
    """Structured outcome of pipeline-style facades' :meth:`arun` / :meth:`run`.

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
        from pyp9m4.serialization import dataclass_to_json_dict

        return dataclass_to_json_dict(self)


class PipelineStdinFacadeBase(ABC):
    """Shared resolver, cwd/env, encoding, timeout defaults, and optional executable override."""

    __slots__ = (
        "_cwd",
        "_default_timeout_s",
        "_encoding",
        "_env",
        "_errors",
        "_exe_override",
        "_resolver",
    )

    _resolver_tool: ClassVar[str]

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        executable_override: Path | str | None = None,
    ) -> None:
        self._resolver = resolver or BinaryResolver()
        self._exe_override = Path(executable_override) if executable_override is not None else None
        self._default_timeout_s = timeout_s
        self._cwd = Path(cwd).resolve() if cwd is not None else None
        self._env = dict(env) if env is not None else None
        self._encoding = encoding
        self._errors = errors

    def _resolved_exe(self) -> Path:
        return self._exe_override or self._resolver.resolve(self._resolver_tool)

    def _inv_from_argv_tail(
        self,
        argv_tail: tuple[str, ...],
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return SubprocessInvocation(
            argv=(os.fspath(self._resolved_exe()), *argv_tail),
            cwd=self._cwd,
            env=self._env,
            stdin=stdin,
            timeout_s=timeout_s,
            encoding=self._encoding,
            errors=self._errors,
        )

    async def _arun_argv(
        self,
        argv_tail: tuple[str, ...],
        stdin: str | bytes | None,
        *,
        timeout_s: float | None,
    ) -> PipelineToolResult:
        inv = self._inv_from_argv_tail(argv_tail, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        return _pipeline_result_from_run(res)


class Isofilter(PipelineStdinFacadeBase):
    """``isofilter`` with constructor defaults, merged call overrides, and parsed text bundles."""

    _resolver_tool = "isofilter"
    __slots__ = ("_instance_options",)

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
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"Isofilter: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=isofilter_executable,
        )
        base = options if options is not None else IsofilterCliOptions()
        self._instance_options = replace(base, **iso_kw)

    @property
    def default_options(self) -> IsofilterCliOptions:
        return self._instance_options

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
        return tuple(opts.to_argv())

    def _build_inv(
        self,
        opts: IsofilterCliOptions,
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return self._inv_from_argv_tail(self._build_argv(opts), stdin=stdin, timeout_s=timeout_s)

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: IsofilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(self._build_argv(opts), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: IsofilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class Isofilter2(Isofilter):
    """``isofilter2`` — same CLI shape as :class:`Isofilter`; uses :class:`~pyp9m4.options.isofilter.IsofilterCliOptions`."""

    _resolver_tool = "isofilter2"
    __slots__ = ()

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
        isofilter2_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        if "isofilter_executable" in kwargs:
            raise TypeError("Isofilter2: use isofilter2_executable=, not isofilter_executable=")
        super().__init__(
            resolver=resolver,
            options=options,
            timeout_s=timeout_s,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            isofilter_executable=isofilter2_executable,
            **kwargs,
        )


IsomorphismFilter = Isofilter
IsomorphismFilter2 = Isofilter2


class Interpformat(PipelineStdinFacadeBase):
    """``interpformat`` (``modelformat``) with defaults, merged overrides, and parsed text bundles."""

    _resolver_tool = "interpformat"
    __slots__ = ("_instance_options",)

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
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"Interpformat: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=interpformat_executable,
        )
        base = options if options is not None else InterpformatCliOptions()
        self._instance_options = replace(base, **ifc_kw)

    @property
    def default_options(self) -> InterpformatCliOptions:
        return self._instance_options

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
        return tuple(opts.to_argv())

    def _build_inv(
        self,
        opts: InterpformatCliOptions,
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return self._inv_from_argv_tail(self._build_argv(opts), stdin=stdin, timeout_s=timeout_s)

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: InterpformatCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(self._build_argv(opts), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: InterpformatCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


InterpFormat = Interpformat


class Prooftrans(PipelineStdinFacadeBase):
    """``prooftrans`` with defaults, merged overrides, and parsed text bundles."""

    _resolver_tool = "prooftrans"
    __slots__ = ("_instance_options",)

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
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"Prooftrans: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=prooftrans_executable,
        )
        base = options if options is not None else ProofTransCliOptions()
        self._instance_options = replace(base, **pt_kw)

    @property
    def default_options(self) -> ProofTransCliOptions:
        return self._instance_options

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
        return tuple(opts.to_argv())

    def _build_inv(
        self,
        opts: ProofTransCliOptions,
        *,
        stdin: str | bytes | None,
        timeout_s: float | None,
    ) -> SubprocessInvocation:
        return self._inv_from_argv_tail(self._build_argv(opts), stdin=stdin, timeout_s=timeout_s)

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: ProofTransCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(self._build_argv(opts), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: ProofTransCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


ProofTrans = Prooftrans


class InterpFilter(PipelineStdinFacadeBase):
    """``interpfilter``: interpretations on stdin; formulas file and test name as argv."""

    _resolver_tool = "interpfilter"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: InterpfilterCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        interpfilter_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        ifl_kw, fac_kw = _split_kwargs(_IFL_FIELDS, "InterpFilter", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"InterpFilter: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=interpfilter_executable,
        )
        base = options if options is not None else InterpfilterCliOptions()
        self._instance_options = replace(base, **ifl_kw)

    @property
    def default_options(self) -> InterpfilterCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: InterpfilterCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[InterpfilterCliOptions, float | None]:
        ifl_kw, fac_kw = _split_kwargs(_IFL_FIELDS, "InterpFilter", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **ifl_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _argv_for(
        self,
        opts: InterpfilterCliOptions,
        *,
        formulas_file: Path | str,
        test: str,
    ) -> tuple[str, ...]:
        return (*opts.to_argv(), os.fspath(formulas_file), test)

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        formulas_file: Path | str,
        test: str,
        options: InterpfilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(self._argv_for(opts, formulas_file=formulas_file, test=test), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        formulas_file: Path | str,
        test: str,
        options: InterpfilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(
            lambda: self.arun(input, formulas_file=formulas_file, test=test, options=options, **kwargs)
        )


class ClauseFilter(PipelineStdinFacadeBase):
    """``clausefilter``: formula stream on stdin; interpretations file and test name as argv."""

    _resolver_tool = "clausefilter"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: ClausefilterCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        clausefilter_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        clf_kw, fac_kw = _split_kwargs(_CLF_FIELDS, "ClauseFilter", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"ClauseFilter: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=clausefilter_executable,
        )
        base = options if options is not None else ClausefilterCliOptions()
        self._instance_options = replace(base, **clf_kw)

    @property
    def default_options(self) -> ClausefilterCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: ClausefilterCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[ClausefilterCliOptions, float | None]:
        clf_kw, fac_kw = _split_kwargs(_CLF_FIELDS, "ClauseFilter", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **clf_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _argv_for(
        self,
        opts: ClausefilterCliOptions,
        *,
        interpretations_file: Path | str,
        test: str,
    ) -> tuple[str, ...]:
        return (*opts.to_argv(), os.fspath(interpretations_file), test)

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        interpretations_file: Path | str,
        test: str,
        options: ClausefilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(
            self._argv_for(opts, interpretations_file=interpretations_file, test=test),
            stdin,
            timeout_s=timeout_s,
        )

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        interpretations_file: Path | str,
        test: str,
        options: ClausefilterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(
            lambda: self.arun(
                input,
                interpretations_file=interpretations_file,
                test=test,
                options=options,
                **kwargs,
            )
        )


class ClauseTester(PipelineStdinFacadeBase):
    """``clausetester``: formula stream on stdin; interpretations file as argv."""

    _resolver_tool = "clausetester"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: ClausetesterCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        clausetester_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        ct_kw, fac_kw = _split_kwargs(_CT_FIELDS, "ClauseTester", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"ClauseTester: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=clausetester_executable,
        )
        base = options if options is not None else ClausetesterCliOptions()
        self._instance_options = replace(base, **ct_kw)

    @property
    def default_options(self) -> ClausetesterCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: ClausetesterCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[ClausetesterCliOptions, float | None]:
        ct_kw, fac_kw = _split_kwargs(_CT_FIELDS, "ClauseTester", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **ct_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _argv_for(self, opts: ClausetesterCliOptions, *, interp_file: Path | str) -> tuple[str, ...]:
        return (os.fspath(interp_file), *opts.to_argv())

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        interp_file: Path | str,
        options: ClausetesterCliOptions | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str | None = None,
        errors: str | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        eff_cwd = Path(cwd).resolve() if cwd is not None else self._cwd
        eff_env = dict(env) if env is not None else self._env
        eff_enc = encoding if encoding is not None else self._encoding
        eff_err = errors if errors is not None else self._errors
        inv = SubprocessInvocation(
            argv=(os.fspath(self._resolved_exe()), *self._argv_for(opts, interp_file=interp_file)),
            cwd=eff_cwd,
            env=eff_env,
            stdin=stdin,
            timeout_s=timeout_s,
            encoding=eff_enc,
            errors=eff_err,
        )
        res = await AsyncToolRunner().run(inv)
        return _pipeline_result_from_run(res)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        interp_file: Path | str,
        options: ClausetesterCliOptions | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str | None = None,
        errors: str | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(
            lambda: self.arun(
                input,
                interp_file=interp_file,
                options=options,
                cwd=cwd,
                env=env,
                encoding=encoding,
                errors=errors,
                **kwargs,
            )
        )


class Rewriter(PipelineStdinFacadeBase):
    """``rewriter``: term stream on stdin; demodulators file as argv."""

    _resolver_tool = "rewriter"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: RewriterCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        rewriter_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        rw_kw, fac_kw = _split_kwargs(_RW_FIELDS, "Rewriter", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"Rewriter: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=rewriter_executable,
        )
        base = options if options is not None else RewriterCliOptions()
        self._instance_options = replace(base, **rw_kw)

    @property
    def default_options(self) -> RewriterCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: RewriterCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[RewriterCliOptions, float | None]:
        rw_kw, fac_kw = _split_kwargs(_RW_FIELDS, "Rewriter", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **rw_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    def _argv_for(self, opts: RewriterCliOptions, *, demod_file: Path | str) -> tuple[str, ...]:
        return (*opts.to_argv(), os.fspath(demod_file))

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        demod_file: Path | str,
        options: RewriterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(self._argv_for(opts, demod_file=demod_file), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        demod_file: Path | str,
        options: RewriterCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, demod_file=demod_file, options=options, **kwargs))


class TptpToLadr(PipelineStdinFacadeBase):
    """``tptp_to_ladr``: TPTP text on stdin."""

    _resolver_tool = "tptp_to_ladr"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: TptpToLadrCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        tptp_to_ladr_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        t_kw, fac_kw = _split_kwargs(_T2L_FIELDS, "TptpToLadr", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"TptpToLadr: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=tptp_to_ladr_executable,
        )
        base = options if options is not None else TptpToLadrCliOptions()
        self._instance_options = replace(base, **t_kw)

    @property
    def default_options(self) -> TptpToLadrCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: TptpToLadrCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[TptpToLadrCliOptions, float | None]:
        t_kw, fac_kw = _split_kwargs(_T2L_FIELDS, "TptpToLadr", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **t_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: TptpToLadrCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(tuple(opts.to_argv()), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: TptpToLadrCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class LadrToTptp(PipelineStdinFacadeBase):
    """``ladr_to_tptp``: LADR-oriented input on stdin."""

    _resolver_tool = "ladr_to_tptp"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: LadrToTptpCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        ladr_to_tptp_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        l_kw, fac_kw = _split_kwargs(_L2T_FIELDS, "LadrToTptp", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"LadrToTptp: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=ladr_to_tptp_executable,
        )
        base = options if options is not None else LadrToTptpCliOptions()
        self._instance_options = replace(base, **l_kw)

    @property
    def default_options(self) -> LadrToTptpCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: LadrToTptpCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[LadrToTptpCliOptions, float | None]:
        l_kw, fac_kw = _split_kwargs(_L2T_FIELDS, "LadrToTptp", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **l_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: LadrToTptpCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(tuple(opts.to_argv()), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: LadrToTptpCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class Renamer(PipelineStdinFacadeBase):
    """``renamer``: stdin/argv shape depends on the LADR build — use :attr:`RenamerCliOptions.extra_argv` as needed."""

    _resolver_tool = "renamer"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: RenamerCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        renamer_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        r_kw, fac_kw = _split_kwargs(_RN_FIELDS, "Renamer", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"Renamer: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=renamer_executable,
        )
        base = options if options is not None else RenamerCliOptions()
        self._instance_options = replace(base, **r_kw)

    @property
    def default_options(self) -> RenamerCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: RenamerCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[RenamerCliOptions, float | None]:
        r_kw, fac_kw = _split_kwargs(_RN_FIELDS, "Renamer", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **r_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: RenamerCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(tuple(opts.to_argv()), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: RenamerCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


class TestClauseEval(PipelineStdinFacadeBase):
    """``test_clause_eval``: consult ``test_clause_eval -h``; optional stdin plus :attr:`TestClauseEvalCliOptions.extra_argv`."""

    _resolver_tool = "test_clause_eval"
    __slots__ = ("_instance_options",)

    def __init__(
        self,
        *,
        resolver: BinaryResolver | None = None,
        options: TestClauseEvalCliOptions | None = None,
        timeout_s: float | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str = "replace",
        test_clause_eval_executable: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        t_kw, fac_kw = _split_kwargs(_TCE_FIELDS, "TestClauseEval", dict(kwargs))
        unknown_fac = {k for k in fac_kw if k != "timeout_s"}
        if unknown_fac:
            raise TypeError(f"TestClauseEval: unexpected keyword argument {next(iter(unknown_fac))!r}")
        eff_timeout = fac_kw["timeout_s"] if "timeout_s" in fac_kw else timeout_s
        super().__init__(
            resolver=resolver,
            timeout_s=eff_timeout,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            executable_override=test_clause_eval_executable,
        )
        base = options if options is not None else TestClauseEvalCliOptions()
        self._instance_options = replace(base, **t_kw)

    @property
    def default_options(self) -> TestClauseEvalCliOptions:
        return self._instance_options

    def _effective_options(
        self,
        *,
        options: TestClauseEvalCliOptions | None,
        kwargs: dict[str, Any],
    ) -> tuple[TestClauseEvalCliOptions, float | None]:
        t_kw, fac_kw = _split_kwargs(_TCE_FIELDS, "TestClauseEval", dict(kwargs))
        eff = self._instance_options
        if options is not None:
            eff = options
        eff = replace(eff, **t_kw)
        timeout_s = fac_kw["timeout_s"] if "timeout_s" in fac_kw else self._default_timeout_s
        return eff, timeout_s

    async def arun(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: TestClauseEvalCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        opts, timeout_s = self._effective_options(options=options, kwargs=kwargs)
        stdin = _coerce_stdin(input)
        return await self._arun_argv(tuple(opts.to_argv()), stdin, timeout_s=timeout_s)

    def run(
        self,
        input: str | bytes | Path | None = None,
        *,
        options: TestClauseEvalCliOptions | None = None,
        **kwargs: Any,
    ) -> PipelineToolResult:
        return _sync_run_awaitable(lambda: self.arun(input, options=options, **kwargs))


# Public names matching the plan (Isofilter / Prooftrans remain primary spellings).
__all__ = [
    "PipelineStdinFacadeBase",
    "PipelineToolResult",
    "Isofilter",
    "IsomorphismFilter",
    "Isofilter2",
    "IsomorphismFilter2",
    "Interpformat",
    "InterpFormat",
    "Prooftrans",
    "ProofTrans",
    "InterpFilter",
    "ClauseFilter",
    "ClauseTester",
    "Rewriter",
    "TptpToLadr",
    "LadrToTptp",
    "Renamer",
    "TestClauseEval",
]
