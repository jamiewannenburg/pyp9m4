"""Tests for :mod:`pyp9m4.parsers`."""

from __future__ import annotations

from pyp9m4.parsers.common import parse_equals_key_values, split_ladr_section_blocks
from pyp9m4.parsers.mace4 import (
    Mace4InterpretationBuffer,
    extract_interpretation_blocks,
    parse_mace4_output,
)
from pyp9m4.parsers.pipeline import inspect_pipeline_text, parse_pipeline_tool_output
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
