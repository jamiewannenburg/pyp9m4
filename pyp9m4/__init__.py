"""pyp9m4 — Prover9 / Mace4 (LADR) tooling for Python.

Primary API: :class:`Prover9` and :class:`Mace4` (constructor defaults, per-call overrides,
parsed results, streaming models, and optional background jobs with :func:`job_status_snapshot_to_json_dict`).

Unified tool dispatch: :func:`arun`, :class:`ToolRegistry`, :data:`ToolName`, :func:`normalize_tool_name`.
HTTP-style option bodies: :func:`unwrap_gui_value`, :func:`coerce_mapping`, :func:`cli_options_from_nested_dict`
(also :meth:`Prover9CliOptions.from_nested_dict` and siblings under :mod:`pyp9m4.options`).

Multi-step stdin chains use :func:`pipeline` and :class:`PipelineBuilder`. Lower-level pieces remain
available — see :mod:`pyp9m4.resolver` and :mod:`pyp9m4.runner`. Use :func:`dataclass_to_json_dict` /
:func:`jsonify_for_api` or each type’s :meth:`~object.to_dict` for JSON APIs.
"""

from pyp9m4.job_manager import JobManager, JobManagerError, JobMetadata, ManagedJobSnapshot
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
from pyp9m4.io_kinds import (
    HasInterpretationsFile,
    HasLadrStdinText,
    HasTheoryText,
    IOKind,
)
from pyp9m4.serialization import dataclass_to_json_dict, jsonify_for_api
from pyp9m4.theory import Theory
from pyp9m4.mace4_facade import Mace4, Mace4SearchHandle
from pyp9m4.parsers import (
    Interpretation,
    Model,
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
from pyp9m4.pipeline import ChainResult, ChainStep, PipelineBuilder, pipeline
from pyp9m4.options import (
    cli_options_from_nested_dict,
    coerce_mapping,
    unwrap_gui_value,
)
from pyp9m4.toolkit import ToolRegistry, ToolRunEnvelope, arun, normalize_tool_name
from pyp9m4.resolver import (
    BINARIES_VERSION,
    BinaryResolver,
    BinaryResolverError,
    CachedBinariesError,
    ChecksumMismatchError,
    ToolName,
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
    # Fluent API taxonomy (I/O kinds, theory builder, interpretation names)
    "IOKind",
    "HasTheoryText",
    "HasLadrStdinText",
    "HasInterpretationsFile",
    "Theory",
    "Interpretation",
    "Model",
    # Facades and primary result / handle types
    "Interpformat",
    "Isofilter",
    "PipelineToolResult",
    "Prooftrans",
    "ChainResult",
    "ChainStep",
    "PipelineBuilder",
    "pipeline",
    "ToolRegistry",
    "ToolRunEnvelope",
    "ToolName",
    "arun",
    "normalize_tool_name",
    "cli_options_from_nested_dict",
    "coerce_mapping",
    "unwrap_gui_value",
    "Prover9",
    "Prover9ProofHandle",
    "Prover9ProofResult",
    "ProverOutcome",
    "infer_prover_outcome",
    "Mace4",
    "Mace4SearchHandle",
    # Job lifecycle and polling (e.g. web APIs)
    "JobManager",
    "JobManagerError",
    "JobMetadata",
    "ManagedJobSnapshot",
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
