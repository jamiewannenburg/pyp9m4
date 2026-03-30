"""Tests for :mod:`pyp9m4.parsers`."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyp9m4.parsers import mace4 as mace4_mod
from pyp9m4.parsers.common import parse_equals_key_values, split_ladr_section_blocks
from pyp9m4.parsers.mace4 import (
    Mace4InterpretationBuffer,
    extract_interpretation_blocks,
    parse_mace4_output,
)
from pyp9m4.parsers.pipeline import inspect_pipeline_text, parse_pipeline_tool_output
from pyp9m4.runner import RunStatus, SubprocessInvocation, ToolRunResult
from pyp9m4.parsers.prover9 import parse_prover9_output


SUBSET_TRANS_TAIL = r"""
============================== SEARCH ================================
% Starting search at 0.01 seconds.
given #1 (I,wt=11): 9 member(f1(x,y),x) | -member(z,x) | member(z,y). [resolve(3,a,4,a)].
============================== PROOF =================================
% Proof 1 at 0.01 (+ 0.00) seconds.
% Length of proof is 14.
 18 $F. [ur(12,b,14,a),unit_del(a,15)].
============================== end of proof ==========================
============================== STATISTICS ============================
Given=6. Generated=12. Kept=9. proofs=1. Usable=6. Sos=3. Demods=0. Limbo=0, Disabled=12.
Megabytes=0.03. User_CPU=0.01, System_CPU=0.00, Wall_clock=0.
============================== end of statistics =====================
============================== end of search =========================
THEOREM PROVED
Exiting with 1 proof.
"""


def test_parse_prover9_sections_and_stats() -> None:
    p = parse_prover9_output(SUBSET_TRANS_TAIL)
    assert "PROOF" in p.sections
    assert "$F" in p.sections["PROOF"]
    assert p.statistics["Given"] == "6"
    assert p.statistics["proofs"] == "1"
    assert p.statistics["Megabytes"] == "0.03"
    assert len(p.proof_segments) == 1
    assert p.proof_segments[0].index == 1
    assert "THEOREM PROVED" in p.exit_phrases


def test_parse_equals_key_values() -> None:
    d = parse_equals_key_values("Given=6. Generated=12. Kept=9.")
    assert d["Given"] == "6"
    assert d["Generated"] == "12"
    assert d["Kept"] == "9"


def test_split_sections_duplicate_warning() -> None:
    text = """
============================== A =================================
one
============================== A =================================
two
"""
    sections, warns = split_ladr_section_blocks(text)
    assert sections["A"].strip() == "two"
    assert any(w.message == "duplicate_section_title" for w in warns)


def test_mace4_interpretation_block() -> None:
    sample = """
============================== MODEL =================================
interpretation( 2, [
   function = c1 = 0,
   function = f(0) = 1,
   relation = R(0,0) = 1,
]).
============================== end of model ===========================
"""
    blocks = extract_interpretation_blocks(sample)
    assert len(blocks) == 1
    p = parse_mace4_output(sample)
    assert len(p.interpretations) == 1
    mi = p.interpretations[0]
    assert mi.domain_size == 2
    kinds = {a.kind for a in mi.standard_assignments}
    assert kinds == {"function", "relation"}
    assert mi.functions == {"c1": 0, "f": 1}
    assert mi.relations == {"R": 2}
    assert mi.value_at("c1") == 0
    assert mi.get_value("c1") == 0
    assert mi.model_eval("c1") == 0
    assert mi.value_at("f", 0) == 1
    assert mi.holds("R", 0, 0) is True
    assert mi.as_function("f")(0) == 1
    assert mi.as_relation("R")(0, 0) is True
    assert list(mi.iter_function_entries("f")) == [((0,), 1)]
    assert list(mi.iter_relation_tuples("R")) == [((0, 0), True)]
    assert "Mace4Interpretation" in repr(mi)
    assert "[c1]" in str(mi) and "[R]" in str(mi)
    html = mi._repr_html_()
    assert "<table" in html and "c1" in html and "R" in html


def test_mace4_interpretation_nested_relation_arg() -> None:
    sample = """
interpretation( 2, [
   relation = R(1,(0)) = 1,
]).
"""
    mi = parse_mace4_output(sample).interpretations[0]
    assert mi.holds("R", 1, 0) is True


def test_mace4_interpretation_list_style_function_and_relation() -> None:
    sample = """
interpretation( 2, [number=1, seconds=0], [
        function(a, [ 0 ]),
        relation(P(_), [ 1, 0 ])
]).
"""
    mi = parse_mace4_output(sample).interpretations[0]
    assert mi.domain_size == 2
    assert mi.functions == {"a": 0}
    assert mi.relations == {"P": 1}
    assert mi.value_at("a") == 0
    assert mi.holds("P", 0) is True
    assert mi.holds("P", 1) is False


def test_mace4_interpretation_list_style_binary_relation() -> None:
    sample = """
interpretation( 3, [number=1], [
        function(f, [ 0, 1, 2 ]),
        relation(R(_,_), [1,0,0, 0,1,0, 0,0,1])
]).
"""
    mi = parse_mace4_output(sample).interpretations[0]
    assert mi.domain_size == 3
    assert mi.functions == {"f": 1}
    assert mi.relations == {"R": 2}
    assert mi.value_at("f", 0) == 0
    assert mi.value_at("f", 2) == 2
    assert mi.holds("R", 0, 0) is True
    assert mi.holds("R", 1, 1) is True
    assert mi.holds("R", 2, 2) is True
    assert mi.holds("R", 0, 1) is False


def test_mace4_interpretation_key_errors() -> None:
    sample = """
interpretation( 2, [
   function = f(0) = 1,
   relation = R(0,0) = 1,
]).
"""
    mi = parse_mace4_output(sample).interpretations[0]
    with pytest.raises(KeyError):
        mi.holds("R", 0, 1)
    with pytest.raises(KeyError):
        mi.value_at("f", 1)
    with pytest.raises(KeyError):
        mi.as_relation("Q")
    with pytest.raises(TypeError):
        mi.as_function("f")(0, 1)


def test_mace4_test_clause_writes_interp_and_invokes_run_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    file_contents: list[str] = []
    stdins: list[str | bytes | None] = []

    def fake_run_sync(inv: SubprocessInvocation) -> ToolRunResult:
        file_contents.append(Path(inv.argv[1]).read_text(encoding="utf-8"))
        stdins.append(inv.stdin)
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(mace4_mod, "run_sync", fake_run_sync)
    sample = """interpretation(1, [\n   function = c1 = 0,\n]).\n"""
    mi = parse_mace4_output(sample).interpretations[0]
    r = mi.test_clause("P(x).\n", clausetester_executable=Path("dummy_clausetester"))
    assert r.exit_code == 0
    assert r.stdout == "ok"
    assert len(file_contents) == 1
    assert "interpretation(1" in file_contents[0]
    assert stdins == ["P(x).\n"]


def test_mace4_test_clause_appends_missing_period(monkeypatch: pytest.MonkeyPatch) -> None:
    file_contents: list[str] = []

    def fake_run_sync(inv: SubprocessInvocation) -> ToolRunResult:
        file_contents.append(Path(inv.argv[1]).read_text(encoding="utf-8"))
        return ToolRunResult(
            status=RunStatus.SUCCEEDED,
            argv=inv.argv,
            exit_code=0,
            duration_s=0.0,
        )

    monkeypatch.setattr(mace4_mod, "run_sync", fake_run_sync)
    sample_no_dot = """interpretation(1, [\n   function = c1 = 0,\n])"""
    mi = parse_mace4_output(sample_no_dot + "\n").interpretations[0]
    mi.test_clause("P(x).\n", clausetester_executable=Path("dummy_clausetester"))
    assert file_contents[0].rstrip().endswith(").")


def test_mace4_portable_only() -> None:
    portable = "[ [ 4, [], [ [ \"function\", \"f\", 1, [0, 1, 2, 3] ] ] ] ]"
    p = parse_mace4_output(portable)
    assert len(p.interpretations) == 0
    assert len(p.portable_lists) == 1
    assert isinstance(p.portable_lists[0], list)


def test_mace4_interpretation_buffer_matches_batch() -> None:
    sample = """
============================== MODEL =================================
interpretation( 2, [
   function = c1 = 0,
   function = f(0) = 1,
   relation = R(0,0) = 1,
]).
============================== end of model ===========================
"""
    buf = Mace4InterpretationBuffer()
    mid = len(sample) // 2
    a = buf.feed(sample[:mid])
    assert a == []
    assert "interpretation(" in buf.buffered_tail
    b = buf.feed(sample[mid:])
    assert len(b) == 1
    mi, _w = b[0]
    batch = parse_mace4_output(sample).interpretations[0]
    assert mi.domain_size == batch.domain_size == 2
    assert mi.standard_assignments == batch.standard_assignments
    assert mi.function_entries == batch.function_entries
    assert mi.relation_entries == batch.relation_entries
    assert mi.raw == batch.raw
    assert "end of model" in buf.buffered_tail


def test_mace4_interpretation_buffer_two_blocks_across_feeds() -> None:
    b1 = """interpretation( 1, [
   function = c1 = 0,
])."""
    b2 = """interpretation( 2, [
   function = c1 = 0,
])."""
    buf = Mace4InterpretationBuffer()
    out1 = buf.feed(b1 + b2[:20])
    out2 = buf.feed(b2[20:])
    assert len(out1) == 1
    assert out1[0][0].domain_size == 1
    assert len(out2) == 1
    assert out2[0][0].domain_size == 2


def test_mace4_portable_chunked_not_parsed_by_buffer() -> None:
    portable = "[ [ 4, [], [ [ \"function\", \"f\", 1, [0, 1, 2, 3] ] ] ] ]"
    buf = Mace4InterpretationBuffer()
    assert buf.feed(portable[:20]) == []
    assert buf.feed(portable[20:]) == []
    full = parse_mace4_output(portable)
    assert len(full.portable_lists) == 1


def test_pipeline_helpers() -> None:
    r = parse_pipeline_tool_output("hello\n% comment\n", "err: something\n")
    assert r.stdout.startswith("hello")
    assert "err:" in r.stderr
    ins = inspect_pipeline_text(r.stdout, r.stderr)
    assert "% comment" in ins.percent_comments
    assert ins.stderr_lines[0] == "err: something"
    assert ins.looks_like_error is False
    ins2 = inspect_pipeline_text("", "Fatal: bad\n")
    assert ins2.looks_like_error is True


def test_pipeline_smoke_prooftrans_like_stdout() -> None:
    """Smoke: pipeline-style tool output with section markers and percent comments."""
    stdout = """% prooftrans output
============================== PROOF =================================
 1 x = x.
============================== end of proof ==========================
"""
    r = parse_pipeline_tool_output(stdout, "")
    ins = inspect_pipeline_text(r.stdout, r.stderr)
    assert any("prooftrans" in c.lower() for c in ins.percent_comments)
    assert "PROOF" in r.stdout
    assert not ins.looks_like_error


def test_mace4_interpretation_buffer_reset_drops_partial() -> None:
    sample = """
interpretation( 2, [
   function = c1 = 0,
]).
"""
    buf = Mace4InterpretationBuffer()
    buf.feed(sample[:30])
    assert extract_interpretation_blocks(buf.buffered_tail) == ()
    buf.reset()
    assert buf.buffered_tail == ""
    out = buf.feed(sample)
    assert len(out) == 1
    assert out[0][0].domain_size == 2


def test_mace4_interpretation_buffer_character_by_character() -> None:
    block = "interpretation( 1, [\n   function = c1 = 0,\n])."
    buf = Mace4InterpretationBuffer()
    completed: list = []
    for ch in block:
        completed.extend(buf.feed(ch))
    assert len(completed) == 1
    assert completed[0][0].domain_size == 1


def test_mace4_interpretation_buffer_nested_parens_in_assignments() -> None:
    """Balanced-paren scan must tolerate parentheses inside the interpretation body."""
    sample = """
interpretation( 2, [
   function = f(0) = 1,
   relation = R(1,(0)) = 1,
]).
"""
    buf = Mace4InterpretationBuffer()
    mid = sample.index("R(1,(0))")
    a = buf.feed(sample[: mid + 4])
    b = buf.feed(sample[mid + 4 :])
    assert a == []
    assert len(b) == 1
    assert b[0][0].domain_size == 2


def test_mace4_interpretation_buffer_warns_when_domain_not_numeric() -> None:
    buf = Mace4InterpretationBuffer()
    bad = """
interpretation( x, [
   function = c1 = 0,
]).
"""
    out = buf.feed(bad)
    assert len(out) == 1
    _mi, warns = out[0]
    assert any(w.message == "domain_size_not_found" for w in warns)
