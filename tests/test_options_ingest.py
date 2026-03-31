"""Tests for :mod:`pyp9m4.options.ingest` and ``from_nested_dict`` on CLI dataclasses."""

from __future__ import annotations

import pytest

from pyp9m4.options import (
    InterpformatCliOptions,
    IsofilterCliOptions,
    Mace4CliOptions,
    ProofTransCliOptions,
    Prover9CliOptions,
    cli_options_from_nested_dict,
    coerce_mapping,
    unwrap_gui_value,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (10, 10),
        ({"value": 10}, 10),
        ({"default": 10}, 10),
        ({"value": {"value": 5}}, 5),
        ({"value": {"default": 3}}, 3),
        ({"not": "wrapper"}, {"not": "wrapper"}),
        ({"value": 1, "extra": 2}, {"value": 1, "extra": 2}),
    ],
)
def test_unwrap_gui_value(raw: object, expected: object) -> None:
    assert unwrap_gui_value(raw) == expected


def test_coerce_mapping_filters_and_aliases() -> None:
    fields_set = frozenset({"a", "b"})
    flat = {"a": 1, "noise": 2, "b": 3}
    assert coerce_mapping(flat, fields_set) == {"a": 1, "b": 3}

    aliased = coerce_mapping(
        {"x": 9, "b": 2},
        fields_set,
        aliases={"x": "a"},
    )
    assert aliased == {"a": 9, "b": 2}


@pytest.mark.parametrize(
    ("direct", "nested_payload"),
    [
        (
            Prover9CliOptions(
                auto2=True,
                parenthesize_output=True,
                max_seconds=30,
                input_files=("a.in", "b.in"),
            ),
            {
                "auto2": True,
                "parenthesize_output": True,
                "max_seconds": {"value": 30},
                "input_files": ["a.in", "b.in"],
            },
        ),
        (
            Prover9CliOptions(),
            {},
        ),
        (
            Prover9CliOptions(),
            None,
        ),
    ],
)
def test_prover9_from_nested_dict_matches_direct(
    direct: Prover9CliOptions,
    nested_payload: dict[str, object] | None,
) -> None:
    assert Prover9CliOptions.from_nested_dict(nested_payload) == direct


@pytest.mark.parametrize(
    ("direct", "nested_payload"),
    [
        (
            Mace4CliOptions(domain_size=3, ignore_unrecognized_assigns=True),
            {"domain_size": {"value": 3}, "ignore_unrecognized_assigns": {"value": True}},
        ),
        (
            Mace4CliOptions(max_seconds=120, verbose=1),
            {"max_seconds": "120", "verbose": 1},
        ),
        (Mace4CliOptions(), None),
    ],
)
def test_mace4_from_nested_dict_matches_direct(
    direct: Mace4CliOptions,
    nested_payload: dict[str, object] | None,
) -> None:
    assert Mace4CliOptions.from_nested_dict(nested_payload) == direct


@pytest.mark.parametrize(
    ("direct", "nested_payload"),
    [
        (
            InterpformatCliOptions(
                style="portable",
                input_file="m.out",
                output_operations="A,B",
            ),
            {
                "style": {"value": "portable"},
                "input_file": "m.out",
                "output_operations": {"default": "A,B"},
            },
        ),
        (InterpformatCliOptions(), {}),
    ],
)
def test_interpformat_from_nested_dict_matches_direct(
    direct: InterpformatCliOptions,
    nested_payload: dict[str, object] | None,
) -> None:
    assert InterpformatCliOptions.from_nested_dict(nested_payload) == direct


@pytest.mark.parametrize(
    ("direct", "nested_payload"),
    [
        (
            IsofilterCliOptions(
                ignore_constants=True,
                check_operations="P",
                discrim_path="d.txt",
            ),
            {
                "ignore_constants": {"value": True},
                "check_operations": "P",
                "discrim_path": {"value": "d.txt"},
            },
        ),
        (IsofilterCliOptions(), None),
    ],
)
def test_isofilter_from_nested_dict_matches_direct(
    direct: IsofilterCliOptions,
    nested_payload: dict[str, object] | None,
) -> None:
    assert IsofilterCliOptions.from_nested_dict(nested_payload) == direct


@pytest.mark.parametrize(
    ("direct", "nested_payload"),
    [
        (
            ProofTransCliOptions(
                mode="hints",
                label="L1",
                expand=True,
                input_file="p9.out",
            ),
            {
                "mode": "hints",
                "label": {"value": "L1"},
                "expand": {"value": True},
                "input_file": "p9.out",
            },
        ),
        (
            ProofTransCliOptions(mode="xml", renumber=True),
            {"mode": {"default": "xml"}, "renumber": "true"},
        ),
        (ProofTransCliOptions(), {}),
    ],
)
def test_prooftrans_from_nested_dict_matches_direct(
    direct: ProofTransCliOptions,
    nested_payload: dict[str, object] | None,
) -> None:
    assert ProofTransCliOptions.from_nested_dict(nested_payload) == direct


def test_cli_options_generic_and_strict_warnings() -> None:
    warns: list[str] = []
    o = cli_options_from_nested_dict(
        Prover9CliOptions,
        {"max_seconds": 5, "unknown_key": 1},
        warnings=warns,
    )
    assert o == Prover9CliOptions(max_seconds=5)
    assert any("unknown_key" in w for w in warns)

    with pytest.raises(ValueError, match="unknown option key"):
        cli_options_from_nested_dict(
            Prover9CliOptions,
            {"foo": 1},
            strict=True,
        )
