"""Thin helpers for interpformat / isofilter / prooftrans text (pipeline tools)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PipelineTextResult:
    """Structured bundle of captured stdout/stderr for pipeline tools."""

    stdout: str
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class PipelineTextInspection:
    """Lightweight inspection of pipeline output text (no process exit code — use :class:`~pyp9m4.runner.ToolRunResult`)."""

    percent_comments: tuple[str, ...]
    """Lines starting with ``%`` (Prover9/LADR style), from stdout."""

    stderr_lines: tuple[str, ...]
    """Non-empty stderr lines."""

    looks_like_error: bool
    """Heuristic: stderr contains ``error`` / ``fatal`` (case-insensitive)."""


_PERCENT_LINE = re.compile(r"^\s*%.*$", re.MULTILINE)
_ERR_HINT = re.compile(r"error|fatal", re.IGNORECASE)


def parse_pipeline_tool_output(stdout: str, stderr: str = "") -> PipelineTextResult:
    """Wrap stdout/stderr strings (identity helper for a consistent pipeline API)."""
    return PipelineTextResult(stdout=stdout, stderr=stderr)


def inspect_pipeline_text(stdout: str, stderr: str = "") -> PipelineTextInspection:
    """Classify common patterns in pipeline tool output for quick UI / logging."""
    pct = tuple(m.group(0).strip() for m in _PERCENT_LINE.finditer(stdout))
    err_lines = tuple(line.strip() for line in stderr.splitlines() if line.strip())
    looks_bad = bool(_ERR_HINT.search(stderr))
    return PipelineTextInspection(
        percent_comments=pct,
        stderr_lines=err_lines,
        looks_like_error=looks_bad,
    )
