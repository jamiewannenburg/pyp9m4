"""Unit tests for :mod:`pyp9m4.mace4_facade`."""

from __future__ import annotations

import pytest

from pyp9m4.mace4_facade import Mace4
from pyp9m4.options.mace4 import Mace4CliOptions
from pyp9m4.resolver import BinaryResolver


def test_mace4_constructor_merge_instance_kwargs_over_options() -> None:
    m = Mace4(options=Mace4CliOptions(domain_size=2), max_models=5, resolver=BinaryResolver())
    assert m.default_options.domain_size == 2
    assert m.default_options.max_models == 5


def test_mace4_effective_call_precedence() -> None:
    m = Mace4(options=Mace4CliOptions(domain_size=2), max_models=1, resolver=BinaryResolver())
    o, _t, _e = m._effective_options(options=None, kwargs={"domain_size": 7})
    assert o.domain_size == 7
    assert o.max_models == 1

    o2, _t2, _e2 = m._effective_options(
        options=Mace4CliOptions(domain_size=3, max_models=9),
        kwargs={"max_models": 10},
    )
    assert o2.domain_size == 3
    assert o2.max_models == 10


def test_mace4_rejects_unknown_kwarg() -> None:
    with pytest.raises(TypeError, match="unexpected keyword"):
        Mace4(resolver=BinaryResolver(), not_a_mace4_field=1)  # type: ignore[call-arg]


def test_counterexamples_delegates_to_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_models(self: Mace4, *a: object, **k: object) -> object:  # noqa: ARG001
        yield from ()

    monkeypatch.setattr(Mace4, "models", _fake_models)
    m = Mace4(resolver=BinaryResolver())
    assert list(m.counterexamples("x")) == []
