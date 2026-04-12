"""Console script entry points that forward to resolved LADR binaries (venv ``Scripts`` / ``bin``)."""

from __future__ import annotations

import os
import sys

from pyp9m4.resolver import BinaryResolver, BinaryResolverError, ToolName


def _run_tool(name: ToolName) -> None:
    try:
        exe = BinaryResolver().resolve(name)
    except BinaryResolverError as e:
        print(f"pyp9m4: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    argv = [os.fspath(exe), *sys.argv[1:]]
    os.execv(os.fspath(exe), argv)


def prover9_main() -> None:
    _run_tool("prover9")


def mace4_main() -> None:
    _run_tool("mace4")


def interpformat_main() -> None:
    _run_tool("interpformat")


def isofilter_main() -> None:
    _run_tool("isofilter")


def prooftrans_main() -> None:
    _run_tool("prooftrans")


def clausetester_main() -> None:
    _run_tool("clausetester")

def autosketches4_main() -> None:
    _run_tool("autosketches4")

def clausefilter_main() -> None:
    _run_tool("clausefilter")

def complex_main() -> None:
    _run_tool("complex")

def directproof_main() -> None:
    _run_tool("directproof")

def dprofiles_main() -> None:
    _run_tool("dprofiles")

def fof_prover9_main() -> None:
    _run_tool("fof-prover9")

def gen_trc_defs_main() -> None:
    _run_tool("gen_trc_defs")

def idfilter_main() -> None:
    _run_tool("idfilter")

def isofilter0_main() -> None:
    _run_tool("isofilter0")

def isofilter2_main() -> None:
    _run_tool("isofilter2")

def ladr_to_tptp_main() -> None:
    _run_tool("ladr_to_tptp")

def latfilter_main() -> None:
    _run_tool("latfilter")

def looper_main() -> None:
    _run_tool("looper")

def miniscope_main() -> None:
    _run_tool("miniscope")

def mirror_flip_main() -> None:
    _run_tool("mirror-flip")

def newauto_main() -> None:
    _run_tool("newauto")

def newsax_main() -> None:
    _run_tool("newsax")

def olfilter_main() -> None:
    _run_tool("olfilter")

def perm3_main() -> None:
    _run_tool("perm3")

def renamer_main() -> None:
    _run_tool("renamer")

def rewriter_main() -> None:
    _run_tool("rewriter")

def sigtest_main() -> None:
    _run_tool("sigtest")

def test_clause_eval_main() -> None:
    _run_tool("test_clause_eval")

def test_complex_main() -> None:
    _run_tool("test_complex")

def tptp_to_ladr_main() -> None:
    _run_tool("tptp_to_ladr")

def unfast_main() -> None:
    _run_tool("unfast")
    
def upper_covers_main() -> None:
    _run_tool("upper-covers")
