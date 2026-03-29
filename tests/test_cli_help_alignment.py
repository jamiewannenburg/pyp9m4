"""CI-oriented checks: documented CLI tokens must appear in each binary's help text."""

from __future__ import annotations

import pytest

from pyp9m4.options import (
    assert_help_text_covers_tokens,
    fetch_tool_help_text,
    iter_tool_cli_doc_specs,
)
from pyp9m4.resolver import BinaryResolver


@pytest.mark.integration
def test_cli_help_text_matches_curated_tokens() -> None:
    """Requires LADR binaries (cached download or ``LADR_BIN_DIR``)."""
    resolver = BinaryResolver()
    for spec in iter_tool_cli_doc_specs():
        exe = resolver.resolve(spec.tool)
        text = fetch_tool_help_text(
            exe,
            spec.help_argv,
            stdin=spec.stdin,
            timeout_s=60.0,
        )
        assert_help_text_covers_tokens(
            text,
            spec.documented_substrings,
            tool_label=spec.tool,
        )
