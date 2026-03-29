"""Normalize CLI help output and verify it still mentions every documented switch."""

from __future__ import annotations

import subprocess
from pathlib import Path
def normalize_help_text(text: str) -> str:
    """Collapse whitespace so comparisons are stable across platforms."""
    return " ".join(text.split())


def fetch_tool_help_text(
    executable: Path | str,
    help_argv: tuple[str, ...],
    *,
    stdin: str | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Run ``executable *help_argv`` and return combined stdout/stderr."""
    exe = Path(executable)
    if stdin is None:
        proc = subprocess.run(
            [os_fspath(exe), *help_argv],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    else:
        proc = subprocess.run(
            [os_fspath(exe), *help_argv],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    return (proc.stdout or "") + (proc.stderr or "")


def os_fspath(p: Path | str) -> str:
    return p if isinstance(p, str) else p.__fspath__()


def assert_help_text_covers_tokens(
    help_text: str,
    required_substrings: tuple[str, ...],
    *,
    tool_label: str,
) -> None:
    """Raise AssertionError if any documented token is missing from help output."""
    normalized = normalize_help_text(help_text).lower()
    missing = [tok for tok in required_substrings if tok.lower() not in normalized]
    if missing:
        raise AssertionError(
            f"{tool_label}: help text missing documented token(s): {missing!r}\n"
            f"--- normalized help (first 2000 chars) ---\n{normalized[:2000]}"
        )
