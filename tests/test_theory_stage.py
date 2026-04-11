"""Theory → Stage fluent chain construction (no subprocess)."""

from __future__ import annotations

from pyp9m4 import Theory
from pyp9m4.io_kinds import IOKind
from pyp9m4.pipe import Stage


def test_theory_to_stage_kind() -> None:
    st = Theory(goals=["P."]).to_stage()
    assert st.out_kind == IOKind.THEORY
    assert "formulas(goals)" in st.initial_stdin
    assert not st.invocations


def test_theory_mace4_single_invocation() -> None:
    s = Theory(goals=["P."]).mace4(domain_size=2)
    assert len(s.invocations) == 1
    assert "mace4" in str(s.invocations[0].argv[0]).lower()


def test_theory_mace4_eliminate_isomorphic_expands() -> None:
    s = Theory(goals=["P."]).mace4(domain_size=2, eliminate_isomorphic=True)
    assert len(s.invocations) == 3
    assert "interpformat" in str(s.invocations[1].argv[0]).lower()
    assert "isofilter" in str(s.invocations[2].argv[0]).lower()


def test_interpfilter_formulas_temp_cleanup_registered() -> None:
    s = (
        Stage.source("", kind=IOKind.INTERPRETATIONS)
        .interpfilter(formulas="P(x).\n", test="all_true")
    )
    assert len(s.cleanup_paths) == 1


def test_theory_prover9_argv() -> None:
    s = Theory(goals=["P."]).prover9()
    assert len(s.invocations) == 1
    assert "prover9" in str(s.invocations[0].argv[0]).lower()
