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
    "run_sync",
    "stream_events_sync",
]

__version__ = "0.1.0"
