"""Unit tests for :mod:`pyp9m4.options` argv builders (no binaries required)."""

from __future__ import annotations

from pyp9m4.options import (
    InterpformatCliOptions,
    IsofilterCliOptions,
    Mace4CliOptions,
    ProofTransCliOptions,
    Prover9CliOptions,
)


def test_prover9_cli_argv_empty() -> None:
    assert Prover9CliOptions().to_argv() == []


def test_prover9_cli_argv_full() -> None:
    o = Prover9CliOptions(
        auto2=True,
        parenthesize_output=True,
        max_seconds=30,
        input_files=("a.in", "b.in"),
    )
    assert o.to_argv() == ["-x", "-p", "-t", "30", "-f", "a.in", "b.in"]


def test_mace4_cli_argv_flag_and_parm() -> None:
    o = Mace4CliOptions(domain_size=3, ignore_unrecognized_assigns=True)
    assert o.to_argv() == ["-n", "3", "-c"]


def test_interpformat_cli_argv() -> None:
    o = InterpformatCliOptions(
        style="portable",
        input_file="m.out",
        output_operations="A,B",
    )
    assert o.to_argv() == ["-f", "m.out", "portable", "output", "A,B"]


def test_isofilter_cli_argv() -> None:
    o = IsofilterCliOptions(
        ignore_constants=True,
        check_operations="P",
        discrim_path="d.txt",
    )
    assert o.to_argv() == ["ignore_constants", "check", "P", "discrim", "d.txt"]


def test_prooftrans_cli_hints_label() -> None:
    o = ProofTransCliOptions(
        mode="hints",
        label="L1",
        expand=True,
        input_file="p9.out",
    )
    assert o.to_argv() == ["hints", "-label", "L1", "expand", "-f", "p9.out"]
