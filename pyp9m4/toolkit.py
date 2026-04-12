"""Unified registry and :func:`arun` entry point for LADR tools (delegates to facades)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pyp9m4.jobs import JobLifecycle
from pyp9m4.mace4_facade import Mace4
from pyp9m4.options.clausefilter import ClausefilterCliOptions
from pyp9m4.options.clausetester import ClausetesterCliOptions
from pyp9m4.options.interpfilter import InterpfilterCliOptions
from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.ladr_to_tptp import LadrToTptpCliOptions
from pyp9m4.options.mace4 import Mace4CliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.options.prover9 import Prover9CliOptions
from pyp9m4.options.renamer import RenamerCliOptions
from pyp9m4.options.rewriter import RewriterCliOptions
from pyp9m4.options.test_clause_eval import TestClauseEvalCliOptions
from pyp9m4.options.tptp_to_ladr import TptpToLadrCliOptions
from pyp9m4.parsers.mace4 import (
    Mace4Interpretation,
    Mace4StdoutMetadata,
    mace4_interpretations_only_stdout,
    parse_mace4_output,
    parse_mace4_stdout_metadata,
)
from pyp9m4.pipeline_facades import (
    ClauseFilter,
    ClauseTester,
    InterpFilter,
    Interpformat,
    Isofilter,
    Isofilter2,
    LadrToTptp,
    PipelineToolResult,
    Prooftrans,
    Renamer,
    Rewriter,
    TestClauseEval,
    TptpToLadr,
)
from pyp9m4.prover9_facade import Prover9, Prover9ProofResult
from pyp9m4.resolver import BinaryResolver, ToolName, UnknownToolError, normalize_resolver_tool_name
from pyp9m4.runner import AsyncToolRunner, RunStatus, ToolRunResult
from pyp9m4.serialization import dataclass_to_json_dict

_ARUN_TOOLS: frozenset[str] = frozenset(
    {
        "prover9",
        "mace4",
        "isofilter",
        "isofilter2",
        "interpformat",
        "prooftrans",
        "interpfilter",
        "clausefilter",
        "clausetester",
        "rewriter",
        "tptp_to_ladr",
        "ladr_to_tptp",
        "renamer",
        "test_clause_eval",
    }
)

_PIPELINE_TOOL_NAMES: frozenset[ToolName] = frozenset(
    (
        "isofilter",
        "isofilter2",
        "interpformat",
        "prooftrans",
        "interpfilter",
        "clausefilter",
        "clausetester",
        "rewriter",
        "tptp_to_ladr",
        "ladr_to_tptp",
        "renamer",
        "test_clause_eval",
    )
)  # type: ignore[assignment]

_ALL_REGISTERED: frozenset[ToolName] = frozenset(_ARUN_TOOLS)  # type: ignore[assignment]


def normalize_tool_name(name: str) -> ToolName:
    """Normalize user input to a :data:`~pyp9m4.resolver.ToolName` supported by :func:`arun`."""
    try:
        key = normalize_resolver_tool_name(name)
    except UnknownToolError as e:
        raise ValueError(str(e)) from e
    if key not in _ARUN_TOOLS:
        raise ValueError(
            f"unknown tool name: {name!r} (not supported by arun; supported: {', '.join(sorted(_ARUN_TOOLS))})"
        )
    return key


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


def _as_interpfilter_options(
    options: InterpfilterCliOptions | Mapping[str, Any] | None,
) -> InterpfilterCliOptions:
    if options is None:
        return InterpfilterCliOptions()
    if isinstance(options, InterpfilterCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return InterpfilterCliOptions(**raw)
    raise TypeError(f"expected InterpfilterCliOptions or mapping, got {type(options).__name__}")


def _as_clausefilter_options(
    options: ClausefilterCliOptions | Mapping[str, Any] | None,
) -> ClausefilterCliOptions:
    if options is None:
        return ClausefilterCliOptions()
    if isinstance(options, ClausefilterCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return ClausefilterCliOptions(**raw)
    raise TypeError(f"expected ClausefilterCliOptions or mapping, got {type(options).__name__}")


def _as_clausetester_options(
    options: ClausetesterCliOptions | Mapping[str, Any] | None,
) -> ClausetesterCliOptions:
    if options is None:
        return ClausetesterCliOptions()
    if isinstance(options, ClausetesterCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return ClausetesterCliOptions(**raw)
    raise TypeError(f"expected ClausetesterCliOptions or mapping, got {type(options).__name__}")


def _as_rewriter_options(
    options: RewriterCliOptions | Mapping[str, Any] | None,
) -> RewriterCliOptions:
    if options is None:
        return RewriterCliOptions()
    if isinstance(options, RewriterCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return RewriterCliOptions(**raw)
    raise TypeError(f"expected RewriterCliOptions or mapping, got {type(options).__name__}")


def _as_tptp_to_ladr_options(
    options: TptpToLadrCliOptions | Mapping[str, Any] | None,
) -> TptpToLadrCliOptions:
    if options is None:
        return TptpToLadrCliOptions()
    if isinstance(options, TptpToLadrCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return TptpToLadrCliOptions(**raw)
    raise TypeError(f"expected TptpToLadrCliOptions or mapping, got {type(options).__name__}")


def _as_ladr_to_tptp_options(
    options: LadrToTptpCliOptions | Mapping[str, Any] | None,
) -> LadrToTptpCliOptions:
    if options is None:
        return LadrToTptpCliOptions()
    if isinstance(options, LadrToTptpCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return LadrToTptpCliOptions(**raw)
    raise TypeError(f"expected LadrToTptpCliOptions or mapping, got {type(options).__name__}")


def _as_renamer_options(
    options: RenamerCliOptions | Mapping[str, Any] | None,
) -> RenamerCliOptions:
    if options is None:
        return RenamerCliOptions()
    if isinstance(options, RenamerCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return RenamerCliOptions(**raw)
    raise TypeError(f"expected RenamerCliOptions or mapping, got {type(options).__name__}")


def _as_test_clause_eval_options(
    options: TestClauseEvalCliOptions | Mapping[str, Any] | None,
) -> TestClauseEvalCliOptions:
    if options is None:
        return TestClauseEvalCliOptions()
    if isinstance(options, TestClauseEvalCliOptions):
        return options
    if isinstance(options, Mapping):
        raw = dict(options)
        if "extra_argv" in raw and not isinstance(raw["extra_argv"], tuple):
            raw["extra_argv"] = tuple(raw["extra_argv"])
        return TestClauseEvalCliOptions(**raw)
    raise TypeError(f"expected TestClauseEvalCliOptions or mapping, got {type(options).__name__}")


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
    ``raw``). Pipeline-style tools populate :attr:`pipeline` (including ``clausetester``).
    For ``mace4``, :attr:`mace4_metadata` holds preamble/statistics; :attr:`raw.stdout` is trimmed
    to ``interpretation(...)`` blocks for chaining.
    """

    program: ToolName
    raw: ToolRunResult | None
    prover9: Prover9ProofResult | None = None
    mace4_models: tuple[Mace4Interpretation, ...] | None = None
    pipeline: PipelineToolResult | None = None
    mace4_metadata: Mace4StdoutMetadata | None = None

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
        if self.mace4_metadata is not None:
            out["mace4_metadata"] = dataclass_to_json_dict(self.mace4_metadata)
        return out


def _finalize_mace4_tool_run(
    res: ToolRunResult,
    *,
    models: tuple[Mace4Interpretation, ...] | None = None,
) -> tuple[ToolRunResult, Mace4StdoutMetadata, tuple[Mace4Interpretation, ...]]:
    meta = parse_mace4_stdout_metadata(res.stdout, stderr=res.stderr)
    interps = models if models is not None else tuple(parse_mace4_output(res.stdout).interpretations)
    trimmed = replace(res, stdout=mace4_interpretations_only_stdout(res.stdout))
    return trimmed, meta, interps


class ToolRegistry:
    """Maps tool names to facade instances (plus resolver); use :meth:`get` or :func:`arun`."""

    __slots__ = (
        "_clausefilter",
        "_clausetester",
        "_interpfilter",
        "_interpformat",
        "_isofilter",
        "_isofilter2",
        "_ladr_to_tptp",
        "_mace4",
        "_prooftrans",
        "_prover9",
        "_renamer",
        "_resolver",
        "_rewriter",
        "_test_clause_eval",
        "_tptp_to_ladr",
    )

    def __init__(self, *, resolver: BinaryResolver | None = None) -> None:
        self._resolver = resolver or BinaryResolver()
        self._prover9 = Prover9(resolver=self._resolver)
        self._mace4 = Mace4(resolver=self._resolver)
        self._isofilter = Isofilter(resolver=self._resolver)
        self._isofilter2 = Isofilter2(resolver=self._resolver)
        self._interpformat = Interpformat(resolver=self._resolver)
        self._prooftrans = Prooftrans(resolver=self._resolver)
        self._interpfilter = InterpFilter(resolver=self._resolver)
        self._clausefilter = ClauseFilter(resolver=self._resolver)
        self._clausetester = ClauseTester(resolver=self._resolver)
        self._rewriter = Rewriter(resolver=self._resolver)
        self._tptp_to_ladr = TptpToLadr(resolver=self._resolver)
        self._ladr_to_tptp = LadrToTptp(resolver=self._resolver)
        self._renamer = Renamer(resolver=self._resolver)
        self._test_clause_eval = TestClauseEval(resolver=self._resolver)

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
    def isofilter2(self) -> Isofilter2:
        return self._isofilter2

    @property
    def interpformat(self) -> Interpformat:
        return self._interpformat

    @property
    def prooftrans(self) -> Prooftrans:
        return self._prooftrans

    @property
    def interpfilter(self) -> InterpFilter:
        return self._interpfilter

    @property
    def clausefilter(self) -> ClauseFilter:
        return self._clausefilter

    @property
    def clausetester(self) -> ClauseTester:
        return self._clausetester

    @property
    def rewriter(self) -> Rewriter:
        return self._rewriter

    @property
    def tptp_to_ladr(self) -> TptpToLadr:
        return self._tptp_to_ladr

    @property
    def ladr_to_tptp(self) -> LadrToTptp:
        return self._ladr_to_tptp

    @property
    def renamer(self) -> Renamer:
        return self._renamer

    @property
    def test_clause_eval(self) -> TestClauseEval:
        return self._test_clause_eval

    def get(
        self, program: ToolName | str
    ) -> (
        Prover9
        | Mace4
        | Isofilter
        | Isofilter2
        | Interpformat
        | Prooftrans
        | InterpFilter
        | ClauseFilter
        | ClauseTester
        | Rewriter
        | TptpToLadr
        | LadrToTptp
        | Renamer
        | TestClauseEval
    ):
        """Return the facade for a tool supported by :func:`arun`."""
        name = normalize_tool_name(str(program))
        return {
            "prover9": self._prover9,
            "mace4": self._mace4,
            "isofilter": self._isofilter,
            "isofilter2": self._isofilter2,
            "interpformat": self._interpformat,
            "prooftrans": self._prooftrans,
            "interpfilter": self._interpfilter,
            "clausefilter": self._clausefilter,
            "clausetester": self._clausetester,
            "rewriter": self._rewriter,
            "tptp_to_ladr": self._tptp_to_ladr,
            "ladr_to_tptp": self._ladr_to_tptp,
            "renamer": self._renamer,
            "test_clause_eval": self._test_clause_eval,
        }[name]

    def registered_tool_names(self) -> frozenset[ToolName]:
        """All tool names dispatchable via :func:`arun`."""
        return _ALL_REGISTERED

    def registered_pipeline_tools(self) -> frozenset[ToolName]:
        """Tools whose :func:`arun` path populates :attr:`ToolRunEnvelope.pipeline`."""
        return _PIPELINE_TOOL_NAMES


async def arun(
    program: ToolName | str,
    input: str | bytes | Path | None = None,
    *,
    options: Any = None,
    resolver: BinaryResolver | None = None,
    registry: ToolRegistry | None = None,
    **kwargs: Any,
) -> ToolRunEnvelope:
    """Run a named LADR tool to completion and return a :class:`ToolRunEnvelope`.

    Dispatches to facades. For ``mace4``, this collects all models (same semantics as exhausting
    :meth:`~pyp9m4.mace4_facade.Mace4.amodels`); streaming stays on ``amodels`` / handles.

    For ``clausetester``, pass ``interp_file=``; ``input`` is the clause stream on stdin.

    For ``interpfilter`` / ``clausefilter``, pass ``formulas_file=`` + ``test=`` or
    ``interpretations_file=`` + ``test=`` respectively.
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
            st, code, out, err, interps, m_meta = await m4._arun_isomorphic_pipeline(
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
            return ToolRunEnvelope(
                program="mace4", raw=raw, mace4_models=interps, mace4_metadata=m_meta
            )

        inv = m4._build_inv(eff, stdin=stdin, timeout_s=timeout_s)
        res = await AsyncToolRunner().run(inv)
        res2, meta, models = _finalize_mace4_tool_run(res)
        return ToolRunEnvelope(
            program="mace4", raw=res2, mace4_models=models, mace4_metadata=meta
        )

    if name == "isofilter":
        opts = _as_isofilter_options(options)
        pipe = await reg.isofilter.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="isofilter", raw=raw, pipeline=pipe)

    if name == "isofilter2":
        opts = _as_isofilter_options(options)
        pipe = await reg.isofilter2.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="isofilter2", raw=raw, pipeline=pipe)

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

    if name == "interpfilter":
        formulas_file = kwargs.pop("formulas_file", None)
        test = kwargs.pop("test", None)
        if formulas_file is None or test is None:
            raise ValueError("interpfilter requires keyword-only formulas_file= and test=")
        opts = _as_interpfilter_options(options)
        pipe = await reg.interpfilter.arun(
            input, formulas_file=formulas_file, test=str(test), options=opts, **kwargs
        )
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="interpfilter", raw=raw, pipeline=pipe)

    if name == "clausefilter":
        interpretations_file = kwargs.pop("interpretations_file", None)
        test = kwargs.pop("test", None)
        if interpretations_file is None or test is None:
            raise ValueError("clausefilter requires keyword-only interpretations_file= and test=")
        opts = _as_clausefilter_options(options)
        pipe = await reg.clausefilter.arun(
            input,
            interpretations_file=interpretations_file,
            test=str(test),
            options=opts,
            **kwargs,
        )
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="clausefilter", raw=raw, pipeline=pipe)

    if name == "clausetester":
        interp_file = kwargs.pop("interp_file", None)
        if interp_file is None:
            raise ValueError("clausetester requires keyword-only interp_file= (path to interpretations file)")
        timeout_s = kwargs.pop("timeout_s", None)
        cwd = kwargs.pop("cwd", None)
        env = kwargs.pop("env", None)
        encoding = kwargs.pop("encoding", None)
        errors = kwargs.pop("errors", None)
        opts = _as_clausetester_options(options)
        pipe = await reg.clausetester.arun(
            input,
            interp_file=interp_file,
            options=opts,
            cwd=cwd,
            env=env,
            encoding=encoding,
            errors=errors,
            timeout_s=timeout_s,
            **kwargs,
        )
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="clausetester", raw=raw, pipeline=pipe)

    if name == "rewriter":
        demod_file = kwargs.pop("demod_file", None)
        if demod_file is None:
            raise ValueError("rewriter requires keyword-only demod_file=")
        opts = _as_rewriter_options(options)
        pipe = await reg.rewriter.arun(input, demod_file=demod_file, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="rewriter", raw=raw, pipeline=pipe)

    if name == "tptp_to_ladr":
        opts = _as_tptp_to_ladr_options(options)
        pipe = await reg.tptp_to_ladr.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="tptp_to_ladr", raw=raw, pipeline=pipe)

    if name == "ladr_to_tptp":
        opts = _as_ladr_to_tptp_options(options)
        pipe = await reg.ladr_to_tptp.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="ladr_to_tptp", raw=raw, pipeline=pipe)

    if name == "renamer":
        opts = _as_renamer_options(options)
        pipe = await reg.renamer.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="renamer", raw=raw, pipeline=pipe)

    if name == "test_clause_eval":
        opts = _as_test_clause_eval_options(options)
        pipe = await reg.test_clause_eval.arun(input, options=opts, **kwargs)
        raw = _pipeline_to_tool_run(pipe)
        return ToolRunEnvelope(program="test_clause_eval", raw=raw, pipeline=pipe)

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
