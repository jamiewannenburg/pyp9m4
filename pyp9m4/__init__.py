"""pyp9m4 — Prover9 / Mace4 (LADR) tooling for Python.

Primary API: :class:`Prover9` and :class:`Mace4` (constructor defaults, per-call overrides,
parsed results, streaming models, and optional background jobs with :func:`job_status_snapshot_to_json_dict`).

Lower-level pieces remain available for custom pipelines — see :mod:`pyp9m4.resolver` and
:mod:`pyp9m4.runner`. Use :func:`dataclass_to_json_dict` / :func:`jsonify_for_api` or each type’s
:meth:`~object.to_dict` for JSON APIs.
"""

from pyp9m4.jobs import (
    JobLifecycle,
    JobLifecyclePhase,
    Mace4AsyncJobHandle,
    Mace4JobStatusSnapshot,
    Prover9AsyncJobHandle,
    Prover9JobStatusSnapshot,
    is_job_lifecycle_string,
    job_status_snapshot_to_json_dict,
)
from pyp9m4.serialization import dataclass_to_json_dict, jsonify_for_api
from pyp9m4.mace4_facade import Mace4, Mace4SearchHandle
from pyp9m4.parsers import (
    ParseWarning,
    inspect_pipeline_text,
    parse_mace4_output,
    parse_pipeline_tool_output,
    parse_prover9_output,
)
from pyp9m4.parsers.prover9_outcome import ProverOutcome, infer_prover_outcome
from pyp9m4.pipeline_facades import (
    Interpformat,
    Isofilter,
    PipelineToolResult,
    Prooftrans,
)
from pyp9m4.prover9_facade import Prover9, Prover9ProofHandle, Prover9ProofResult
from pyp9m4.toolkit import ToolRegistry, ToolRunEnvelope, arun, normalize_tool_name
from pyp9m4.resolver import (
    BINARIES_VERSION,
    BinaryResolver,
    BinaryResolverError,
    CachedBinariesError,
    ChecksumMismatchError,
    UnsupportedPlatformError,
    asset_filename_for_platform_key,
    detect_platform_key,
)
from pyp9m4.runner import (
    AsyncToolRunner,
    RunStatus,
    StderrLine,
    StdoutLine,
    StreamEvent,
    SubprocessInvocation,
    SyncToolRunner,
    ToolRunResult,
    run_sync,
    stream_events_sync,
)

__all__ = [
    # Facades and primary result / handle types
    "Interpformat",
    "Isofilter",
    "PipelineToolResult",
    "Prooftrans",
    "ToolRegistry",
    "ToolRunEnvelope",
    "arun",
    "normalize_tool_name",
    "Prover9",
    "Prover9ProofHandle",
    "Prover9ProofResult",
    "ProverOutcome",
    "infer_prover_outcome",
    "Mace4",
    "Mace4SearchHandle",
    # Job lifecycle and polling (e.g. web APIs)
    "JobLifecycle",
    "JobLifecyclePhase",
    "Prover9AsyncJobHandle",
    "Prover9JobStatusSnapshot",
    "Mace4AsyncJobHandle",
    "Mace4JobStatusSnapshot",
    "is_job_lifecycle_string",
    "job_status_snapshot_to_json_dict",
    "dataclass_to_json_dict",
    "jsonify_for_api",
    # Parsers
    "ParseWarning",
    "parse_prover9_output",
    "parse_mace4_output",
    "parse_pipeline_tool_output",
    "inspect_pipeline_text",
    # Binary resolution (also used implicitly by facades)
    "BINARIES_VERSION",
    "BinaryResolver",
    "BinaryResolverError",
    "CachedBinariesError",
    "ChecksumMismatchError",
    "UnsupportedPlatformError",
    "asset_filename_for_platform_key",
    "detect_platform_key",
    # Subprocess / streaming (advanced)
    "AsyncToolRunner",
    "RunStatus",
    "StderrLine",
    "StdoutLine",
    "StreamEvent",
    "SubprocessInvocation",
    "SyncToolRunner",
    "ToolRunResult",
    "run_sync",
    "stream_events_sync",
]

__version__ = "0.1.0"
