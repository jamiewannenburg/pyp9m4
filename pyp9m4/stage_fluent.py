"""Attach ``.mace4()``, ``.prover9()``, … chain methods to :class:`~pyp9m4.pipe.Stage`."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pyp9m4.io_kinds import IOKind
from pyp9m4.runner import SubprocessInvocation


def _res(stage: Any) -> Any:
    from pyp9m4.resolver import BinaryResolver

    return stage.resolver or BinaryResolver()


def _fac_kw(stage: Any) -> dict[str, Any]:
    return {
        "resolver": _res(stage),
        "cwd": stage.cwd,
        "env": stage.env,
        "timeout_s": stage.timeout_s,
    }


def _merge_cleanup(stage: Any, extra: tuple[Path, ...]) -> Any:
    if not extra:
        return stage
    return replace(stage, cleanup_paths=stage.cleanup_paths + extra)


def _stage_mace4(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.mace4_facade import Mace4

    m4 = Mace4(**_fac_kw(self))
    opts, timeout_s, elim = m4._effective_options(options=options, kwargs=dict(kwargs))
    if elim:
        inv_m = m4._build_inv(opts, stdin=None, timeout_s=timeout_s)
        s = self.with_step(
            inv_m,
            produces=IOKind.INTERPRETATIONS,
            expects=IOKind.THEORY,
            output_file=output_file,
        )
        inv_i = SubprocessInvocation(
            argv=(os.fspath(m4._exe_interpformat()), *m4._ifc_default.to_argv()),
            cwd=m4._cwd,
            env=m4._env,
            stdin=None,
            timeout_s=timeout_s,
            encoding=m4._encoding,
            errors=m4._errors,
        )
        s = s.with_step(inv_i, produces=IOKind.INTERPRETATIONS, expects=IOKind.INTERPRETATIONS)
        inv_s = SubprocessInvocation(
            argv=(os.fspath(m4._exe_isofilter()), *m4._iso_default.to_argv()),
            cwd=m4._cwd,
            env=m4._env,
            stdin=None,
            timeout_s=timeout_s,
            encoding=m4._encoding,
            errors=m4._errors,
        )
        return s.with_step(inv_s, produces=IOKind.INTERPRETATIONS, expects=IOKind.INTERPRETATIONS)
    inv = m4._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.INTERPRETATIONS,
        expects=IOKind.THEORY,
        output_file=output_file,
    )


def _stage_prover9(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.prover9_facade import Prover9

    p9 = Prover9(**_fac_kw(self))
    opts, timeout_s = p9._effective_options(options=options, kwargs=dict(kwargs))
    inv = p9._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.PROOFS,
        expects=IOKind.THEORY,
        output_file=output_file,
    )


def _stage_fof_prover9(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    fof_prover9_executable: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.prover9_facade import Prover9

    exe = Path(fof_prover9_executable) if fof_prover9_executable is not None else _res(self).resolve("fof_prover9")
    p9 = Prover9(**_fac_kw(self), prover9_executable=exe)
    opts, timeout_s = p9._effective_options(options=options, kwargs=dict(kwargs))
    inv = p9._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.PROOFS,
        expects=IOKind.THEORY,
        output_file=output_file,
    )


def _iso_stage(
    self: Any,
    *,
    which: str,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import Isofilter, Isofilter2

    kw = dict(kwargs)
    init_extras: dict[str, Any] = {}
    if which == "2":
        if "isofilter2_executable" in kw:
            init_extras["isofilter2_executable"] = kw.pop("isofilter2_executable")
    else:
        if "isofilter_executable" in kw:
            init_extras["isofilter_executable"] = kw.pop("isofilter_executable")
    cls = Isofilter2 if which == "2" else Isofilter
    iso = cls(**{**_fac_kw(self), **init_extras})
    opts, timeout_s = iso._effective_options(options=options, kwargs=dict(kw))
    inv = iso._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.INTERPRETATIONS,
        expects=IOKind.INTERPRETATIONS,
        output_file=output_file,
    )


def _stage_isofilter(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    return _iso_stage(self, which="1", options=options, output_file=output_file, **kwargs)


def _stage_isofilter2(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    return _iso_stage(self, which="2", options=options, output_file=output_file, **kwargs)


def _stage_interpformat(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import Interpformat

    ifc = Interpformat(**_fac_kw(self))
    opts, timeout_s = ifc._effective_options(options=options, kwargs=dict(kwargs))
    inv = ifc._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.INTERPRETATIONS,
        expects=IOKind.INTERPRETATIONS,
        output_file=output_file,
    )


def _stage_prooftrans(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import Prooftrans

    pt = Prooftrans(**_fac_kw(self))
    opts, timeout_s = pt._effective_options(options=options, kwargs=dict(kwargs))
    inv = pt._build_inv(opts, stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.PROOFS,
        expects=IOKind.PROOFS,
        output_file=output_file,
    )


def _stage_interpfilter(
    self: Any,
    formulas_file: Path | str | None = None,
    test: str = "all_true",
    *,
    formulas: str | Sequence[str] | None = None,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import InterpFilter

    extra: tuple[Path, ...] = ()
    if formulas_file is None:
        if formulas is None:
            raise TypeError("interpfilter() requires formulas_file= or formulas=")
        body = formulas if isinstance(formulas, str) else "\n".join(formulas)
        fd, path = tempfile.mkstemp(prefix="pyp9m4-", suffix=".clauses", text=True)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")
        extra = (Path(path),)
        formulas_file = path
    fl = InterpFilter(**_fac_kw(self))
    opts, timeout_s = fl._effective_options(options=options, kwargs=dict(kwargs))
    inv = fl._inv_from_argv_tail(
        fl._argv_for(opts, formulas_file=formulas_file, test=test),
        stdin=None,
        timeout_s=timeout_s,
    )
    nxt = self.with_step(
        inv,
        produces=IOKind.INTERPRETATIONS,
        expects=IOKind.INTERPRETATIONS,
        output_file=output_file,
    )
    return _merge_cleanup(nxt, extra)


def _stage_clausefilter(
    self: Any,
    interpretations_file: Path | str,
    test: str,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import ClauseFilter

    cf = ClauseFilter(**_fac_kw(self))
    opts, timeout_s = cf._effective_options(options=options, kwargs=dict(kwargs))
    inv = cf._inv_from_argv_tail(
        cf._argv_for(opts, interpretations_file=interpretations_file, test=test),
        stdin=None,
        timeout_s=timeout_s,
    )
    return self.with_step(
        inv,
        produces=IOKind.FORMULAS,
        expects=IOKind.FORMULAS,
        output_file=output_file,
    )


def _stage_clausetester(
    self: Any,
    interp_file: Path | str,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import ClauseTester

    ct = ClauseTester(**_fac_kw(self))
    opts, timeout_s = ct._effective_options(options=options, kwargs=dict(kwargs))
    inv = SubprocessInvocation(
        argv=(os.fspath(ct._resolved_exe()), *ct._argv_for(opts, interp_file=interp_file)),
        cwd=ct._cwd,
        env=ct._env,
        stdin=None,
        timeout_s=timeout_s,
        encoding=ct._encoding,
        errors=ct._errors,
    )
    return self.with_step(
        inv,
        produces=IOKind.CLAUSETESTER_REPORT,
        expects=IOKind.FORMULAS,
        output_file=output_file,
    )


def _stage_tptp_to_ladr(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import TptpToLadr

    t = TptpToLadr(**_fac_kw(self))
    opts, timeout_s = t._effective_options(options=options, kwargs=dict(kwargs))
    inv = t._inv_from_argv_tail(tuple(opts.to_argv()), stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.LADR_BARE_INPUT,
        expects=IOKind.TPTP_TEXT,
        output_file=output_file,
    )


def _stage_ladr_to_tptp(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import LadrToTptp

    t = LadrToTptp(**_fac_kw(self))
    opts, timeout_s = t._effective_options(options=options, kwargs=dict(kwargs))
    inv = t._inv_from_argv_tail(tuple(opts.to_argv()), stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.TPTP_TEXT,
        expects=IOKind.THEORY,
        output_file=output_file,
    )


def _stage_rewriter(
    self: Any,
    demod_file: Path | str,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import Rewriter

    rw = Rewriter(**_fac_kw(self))
    opts, timeout_s = rw._effective_options(options=options, kwargs=dict(kwargs))
    inv = rw._inv_from_argv_tail(rw._argv_for(opts, demod_file=demod_file), stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.TERMS,
        expects=IOKind.TERMS,
        output_file=output_file,
    )


def _stage_renamer(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import Renamer

    r = Renamer(**_fac_kw(self))
    opts, timeout_s = r._effective_options(options=options, kwargs=dict(kwargs))
    inv = r._inv_from_argv_tail(tuple(opts.to_argv()), stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.LADR_TEXT,
        expects=IOKind.LADR_TEXT,
        output_file=output_file,
    )


def _stage_test_clause_eval(
    self: Any,
    *,
    options: Any = None,
    output_file: Path | str | None = None,
    **kwargs: Any,
) -> Any:
    from pyp9m4.pipeline_facades import TestClauseEval

    t = TestClauseEval(**_fac_kw(self))
    opts, timeout_s = t._effective_options(options=options, kwargs=dict(kwargs))
    inv = t._inv_from_argv_tail(tuple(opts.to_argv()), stdin=None, timeout_s=timeout_s)
    return self.with_step(
        inv,
        produces=IOKind.LADR_TEXT,
        expects=IOKind.LADR_TEXT,
        output_file=output_file,
    )


def patch_stage(Stage: type) -> None:
    Stage.mace4 = _stage_mace4
    Stage.prover9 = _stage_prover9
    Stage.fof_prover9 = _stage_fof_prover9
    Stage.isofilter = _stage_isofilter
    Stage.isofilter2 = _stage_isofilter2
    Stage.interpformat = _stage_interpformat
    Stage.prooftrans = _stage_prooftrans
    Stage.interpfilter = _stage_interpfilter
    Stage.clausefilter = _stage_clausefilter
    Stage.clausetester = _stage_clausetester
    Stage.tptp_to_ladr = _stage_tptp_to_ladr
    Stage.ladr_to_tptp = _stage_ladr_to_tptp
    Stage.rewriter = _stage_rewriter
    Stage.renamer = _stage_renamer
    Stage.test_clause_eval = _stage_test_clause_eval
