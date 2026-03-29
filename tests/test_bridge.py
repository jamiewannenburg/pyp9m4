"""Tests for ``pyp9m4.bridge`` (TPTP/SMT-LIB helpers; optional PySMT when installed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyp9m4.bridge import pysmt_extra
from pyp9m4.bridge.smtlib import (
    extract_set_logic,
    iter_smtlib_commands,
    read_smtlib_text,
    summarize_commands,
    write_smtlib_text,
)
from pyp9m4.bridge.tptp import (
    iter_include_directives,
    iter_tptp_statements,
    parse_tptp_preamble,
    tptp_statements_as_prover9_comments,
)


def test_parse_tptp_preamble() -> None:
    text = "% Problem : TST001\n% Version : 1.2.3\n"
    p = parse_tptp_preamble(text)
    assert p.problem_name == "TST001"
    assert p.version == "1.2.3"


def test_iter_tptp_statements_and_names() -> None:
    t = (
        "/* hdr */\n"
        "fof(ax, axiom, f).\n"
        "include('foo.p').\n"
        "troll(x, y).\n"
    )
    stmts = list(iter_tptp_statements(t))
    assert [s.kind for s in stmts] == ["fof", "include", "other"]
    assert stmts[0].name == "ax"
    assert "include('foo.p')" in stmts[1].raw


def test_iter_include_directives() -> None:
    assert list(iter_include_directives("include( \"b.p\" ).")) == ["b.p"]


def test_tptp_prover9_comments() -> None:
    t = "fof(a, axiom, p).\n"
    stmts = list(iter_tptp_statements(t))
    c = tptp_statements_as_prover9_comments(stmts)
    assert "TPTP excerpt" in c
    assert "% fof(a, axiom, p)." in c


def test_smtlib_iter_and_set_logic() -> None:
    s = "(set-logic QF_UF)\n(assert true)\n"
    assert extract_set_logic(s) == "QF_UF"
    cmds = list(iter_smtlib_commands(s))
    assert len(cmds) == 2
    heads = [x.head for x in summarize_commands(cmds)]
    assert heads[0] == "set-logic"
    assert heads[1] == "assert"


def test_smtlib_roundtrip_file(tmp_path: Path) -> None:
    p = tmp_path / "t.smt2"
    body = "(set-logic QF_UF)\n"
    write_smtlib_text(p, body)
    assert read_smtlib_text(p) == body


@pytest.mark.skipif(not pysmt_extra.is_pysmt_available(), reason="pysmt extra not installed")
def test_pysmt_read_asserts(tmp_path: Path) -> None:
    p = tmp_path / "x.smt2"
    p.write_text("(set-logic QF_UF)\n(assert true)\n", encoding="utf-8")
    forms = pysmt_extra.read_smtlib_script_as_formulas(p)
    assert len(forms) == 1


@pytest.mark.skipif(not pysmt_extra.is_pysmt_available(), reason="pysmt extra not installed")
def test_pysmt_parse_string() -> None:
    script = pysmt_extra.parse_smtlib_string("(set-logic QF_UF)\n(assert true)\n")
    names = [c.name for c in script.commands]
    assert names == ["set-logic", "assert"]
