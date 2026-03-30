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
