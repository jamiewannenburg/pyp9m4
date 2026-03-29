"""Tests for :mod:`pyp9m4.jobs` status snapshots and protocols."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from pyp9m4.jobs import (
    JobLifecyclePhase,
    Mace4AsyncJobHandle,
    Mace4JobStatusSnapshot,
    Prover9AsyncJobHandle,
    Prover9JobStatusSnapshot,
    is_job_lifecycle_string,
    job_status_snapshot_to_json_dict,
)


def test_job_lifecycle_phase_values() -> None:
    assert JobLifecyclePhase.SUCCEEDED.value == "succeeded"
    assert JobLifecyclePhase.SUCCEEDED == "succeeded"
    assert is_job_lifecycle_string("running")
    assert not is_job_lifecycle_string("nope")


def test_job_status_snapshot_to_json_dict() -> None:
    p = Prover9JobStatusSnapshot(
        lifecycle="succeeded",
        exit_code=0,
        stderr_tail="",
        argv=("prover9",),
        duration_s=1.25,
    )
    d = job_status_snapshot_to_json_dict(p)
    assert d == {
        "lifecycle": "succeeded",
        "exit_code": 0,
        "stderr_tail": "",
        "argv": ["prover9"],
        "duration_s": 1.25,
    }

    m = Mace4JobStatusSnapshot(
        lifecycle="running",
        models_found=2,
        last_domain_size=3,
        current_size_range=(2, 5),
        exit_code=None,
        stderr_tail="warn",
        argv=("mace4", "-n", "2"),
        domain_increment=1,
        duration_s=None,
    )
    dm = job_status_snapshot_to_json_dict(m)
    assert dm["models_found"] == 2
    assert dm["current_size_range"] == [2, 5]
    assert dm["domain_increment"] == 1


def test_job_status_snapshot_to_json_dict_rejects_non_dataclass() -> None:
    with pytest.raises(TypeError):
        job_status_snapshot_to_json_dict("x")  # type: ignore[arg-type]


def test_runtime_checkable_protocols_match_minimal_handles() -> None:
    """Avoid spawning binaries; only verify structural typing for web/registry use."""

    class _MiniProver9Handle:
        async def status(self) -> Prover9JobStatusSnapshot:
            return Prover9JobStatusSnapshot(
                lifecycle="pending", exit_code=None, stderr_tail="", argv=()
            )

        async def wait(self) -> None:
            return None

        async def result(self) -> Any:
            return None

        def cancel(self) -> None:
            return None

    class _MiniMace4Handle:
        async def status(self) -> Mace4JobStatusSnapshot:
            return Mace4JobStatusSnapshot(
                lifecycle="pending",
                models_found=0,
                last_domain_size=None,
                current_size_range=None,
                exit_code=None,
                stderr_tail="",
            )

        async def wait(self) -> None:
            return None

        async def result(self) -> None:
            return None

        def cancel(self) -> None:
            return None

        async def amodels(self) -> AsyncIterator[Any]:
            if False:
                yield None

    assert isinstance(_MiniProver9Handle(), Prover9AsyncJobHandle)
    assert isinstance(_MiniMace4Handle(), Mace4AsyncJobHandle)
