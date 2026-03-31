"""JSON-serializable event dicts for :meth:`~pyp9m4.prover9_facade.Prover9ProofHandle.event_stream`
and :meth:`~pyp9m4.mace4_facade.Mace4SearchHandle.event_stream` (SSE-friendly)."""

from __future__ import annotations

from typing import Any

from pyp9m4.jobs import JobLifecycle
from pyp9m4.parsers.mace4 import Mace4Interpretation
from pyp9m4.serialization import dataclass_to_json_dict


def sse_lifecycle_event(phase: JobLifecycle) -> dict[str, Any]:
    return {"type": "lifecycle_change", "phase": phase}


def sse_stdout_event(line: str) -> dict[str, Any]:
    return {"type": "stdout", "line": line}


def sse_stderr_event(line: str) -> dict[str, Any]:
    return {"type": "stderr", "line": line}


def sse_model_found_event(model: Mace4Interpretation) -> dict[str, Any]:
    return {"type": "model_found", "model": dataclass_to_json_dict(model)}
