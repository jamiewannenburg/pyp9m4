"""pyp9m4 — Prover9 / Mace4 (LADR) tooling for Python."""

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
from pyp9m4.parsers import (
    ParseWarning,
    inspect_pipeline_text,
    parse_mace4_output,
    parse_pipeline_tool_output,
    parse_prover9_output,
)

__all__ = [
    "AsyncToolRunner",
    "BINARIES_VERSION",
    "BinaryResolver",
    "BinaryResolverError",
    "CachedBinariesError",
    "ChecksumMismatchError",
    "RunStatus",
    "StderrLine",
    "StdoutLine",
    "StreamEvent",
    "SubprocessInvocation",
    "SyncToolRunner",
    "ToolRunResult",
    "UnsupportedPlatformError",
    "asset_filename_for_platform_key",
    "detect_platform_key",
    "inspect_pipeline_text",
    "parse_mace4_output",
    "parse_pipeline_tool_output",
    "parse_prover9_output",
    "ParseWarning",
    "run_sync",
    "stream_events_sync",
]

__version__ = "0.1.0"
