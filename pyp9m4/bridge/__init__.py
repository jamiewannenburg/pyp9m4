"""Format bridges: TPTP and SMT-LIB helpers without heavy core dependencies.

- :mod:`pyp9m4.bridge.tptp` — TPTP text I/O, preamble metadata, statement iteration, Prover9 comment export.
- :mod:`pyp9m4.bridge.smtlib` — SMT-LIB file I/O, ``set-logic`` extraction, top-level command splitting.
- :mod:`pyp9m4.bridge.pysmt_extra` — optional PySMT integration (requires ``pip install pyp9m4[smt]``).
"""

from __future__ import annotations

from pyp9m4.bridge import pysmt_extra
from pyp9m4.bridge.smtlib import (
    SmtlibCommandSummary,
    extract_set_logic,
    iter_smtlib_commands,
    read_smtlib_text,
    summarize_commands,
    write_smtlib_text,
)
from pyp9m4.bridge.tptp import (
    TptpPreamble,
    TptpStatement,
    iter_include_directives,
    iter_tptp_statements,
    parse_tptp_preamble,
    prover9_interop_note,
    read_tptp_text,
    tptp_statements_as_prover9_comments,
    write_tptp_text,
)

__all__ = [
    "SmtlibCommandSummary",
    "TptpPreamble",
    "TptpStatement",
    "extract_set_logic",
    "iter_include_directives",
    "iter_smtlib_commands",
    "parse_tptp_preamble",
    "prover9_interop_note",
    "pysmt_extra",
    "read_smtlib_text",
    "read_tptp_text",
    "summarize_commands",
    "tptp_statements_as_prover9_comments",
    "write_smtlib_text",
    "write_tptp_text",
]
