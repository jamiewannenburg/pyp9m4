"""Tests for I/O taxonomy: :class:`~pyp9m4.theory.Theory`, :class:`~pyp9m4.io_kinds.IOKind`, aliases."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pyp9m4 import (
    HasInterpretationsFile,
    HasTheoryText,
    IOKind,
    Interpretation,
    Interpformat,
    InterpretationFormat,
    Model,
    Theory,
    parse_interpretations_from_file,
    parse_models_from_file,
)
from pyp9m4.parsers import Mace4Interpretation
from pyp9m4.pipe import Stage


def test_theory_from_assumptions_and_goals() -> None:
    t = Theory(assumptions="p.", goals="q.")
    assert "formulas(assumptions)." in str(t)
    assert "p." in str(t)
    assert "formulas(goals)." in str(t)
    assert "q." in str(t)
    assert str(t).count("end_of_list.") == 2
    assert t.to_theory_text() == str(t)


def test_theory_text_escape_hatch() -> None:
    raw = "formulas(assumptions).\na.\nend_of_list.\n"
    t = Theory(goals="ignored", text=raw)
    assert str(t) == raw
    assert "ignored" not in str(t)


def test_theory_options_prefix() -> None:
    t = Theory(options="set(auto).", assumptions="a.", goals="")
    s = str(t)
    assert s.startswith("set(auto).\n")
    assert "formulas(assumptions)." in s


def test_theory_sequence_assumptions() -> None:
    t = Theory(assumptions=["p.", "q."], goals=())
    body = str(t)
    assert "p." in body and "q." in body


def test_io_kind_enum_values() -> None:
    assert IOKind.THEORY.value == "theory"
    assert IOKind.INTERPRETATIONS_FILE.value == "interpretations_file"


def test_interpretation_model_alias() -> None:
    assert Interpretation is Mace4Interpretation
    assert Model is Interpretation


def test_has_theory_text_runtime_check() -> None:
    t = Theory(assumptions="p.", goals="q.")
    assert isinstance(t, HasTheoryText)


def test_has_interpretations_file_protocol() -> None:
    class _Side:
        interpretations_path = Path("models.out")

    assert isinstance(_Side(), HasInterpretationsFile)
    assert _Side().interpretations_path == Path("models.out")


def test_theory_repr_truncates_long_text() -> None:
    long = "x\n" * 50
    r = repr(Theory(text=long))
    assert "…" in r
    assert "chars" in r


def test_theory_from_file_path(tmp_path: Path) -> None:
    p = tmp_path / "t.in"
    p.write_text("formulas(assumptions).\na.\nend_of_list.\n", encoding="utf-8")
    t = Theory.from_file(p)
    assert "formulas(assumptions)" in str(t)


def test_theory_from_file_bytesio() -> None:
    bio = BytesIO(b"formulas(goals).\np.\nend_of_list.\n")
    t = Theory.from_file(bio)
    assert "p." in str(t)


def test_parse_interpretations_from_file(tmp_path: Path) -> None:
    snippet = """interpretation( 3, [number=1, seconds=0], [

        function(e, [ 0 ]),

]).
"""
    p = tmp_path / "m.out"
    p.write_text(snippet, encoding="utf-8")
    got = list(parse_interpretations_from_file(p))
    assert len(got) == 1
    assert got[0].domain_size == 3
    assert parse_models_from_file is parse_interpretations_from_file


def test_interpformat_from_file_models(tmp_path: Path) -> None:
    p = tmp_path / "m.out"
    p.write_text("interpretation( 1, [], []).\n", encoding="utf-8")
    m = list(Interpformat.from_file(p).models())
    assert len(m) == 1
    assert m[0].domain_size == 1
    assert InterpretationFormat is Interpformat


def test_stage_from_file(tmp_path: Path) -> None:
    p = tmp_path / "t.in"
    p.write_text("x.", encoding="utf-8")
    st = Stage.from_file(p, kind=IOKind.FORMULAS)
    assert st.initial_stdin == b"x."
