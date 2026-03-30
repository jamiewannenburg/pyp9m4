"""Tests for :mod:`pyp9m4.parsers.prover9_outcome`."""

from __future__ import annotations

from pyp9m4.parsers.prover9 import parse_prover9_output
from pyp9m4.parsers.prover9_outcome import ProverOutcome, infer_prover_outcome


def test_infer_proved_from_theorem_proved_line() -> None:
    p = parse_prover9_output("THEOREM PROVED\n")
    o = infer_prover_outcome(p, lifecycle="succeeded", exit_code=0, stdout="THEOREM PROVED\n")
    assert o == ProverOutcome.proved


def test_infer_proved_from_statistics_proofs() -> None:
    text = """
============================== STATISTICS ============================
Given=1. proofs=1.
============================== end of statistics =====================
"""
    p = parse_prover9_output(text)
    o = infer_prover_outcome(p, lifecycle="succeeded", exit_code=0, stdout=text)
    assert o == ProverOutcome.proved


def test_infer_not_proved_phrase() -> None:
    p = parse_prover9_output("THEOREM NOT PROVED\n")
    o = infer_prover_outcome(p, lifecycle="succeeded", exit_code=0, stdout="THEOREM NOT PROVED\n")
    assert o == ProverOutcome.not_proved


def test_infer_unknown_when_succeeded_but_unclassified() -> None:
    p = parse_prover9_output("some noise\n")
    o = infer_prover_outcome(p, lifecycle="succeeded", exit_code=0, stdout="some noise\n")
    assert o == ProverOutcome.unknown


def test_lifecycle_failed_is_error() -> None:
    p = parse_prover9_output("")
    o = infer_prover_outcome(p, lifecycle="failed", exit_code=1, stdout="")
    assert o == ProverOutcome.error


def test_lifecycle_timed_out() -> None:
    p = parse_prover9_output("")
    o = infer_prover_outcome(p, lifecycle="timed_out", exit_code=None, stdout="")
    assert o == ProverOutcome.timed_out


def test_lifecycle_cancelled() -> None:
    p = parse_prover9_output("")
    o = infer_prover_outcome(p, lifecycle="cancelled", exit_code=None, stdout="")
    assert o == ProverOutcome.cancelled
