"""Registry of tools, help invocations, and strings that must stay in sync with binaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from pyp9m4.options.interpformat import (
    INTERPFORMAT_DOCUMENTED_HELP_SUBSTRINGS,
    INTERPFORMAT_HELP_ARGV,
)
from pyp9m4.options.isofilter import (
    ISOFILTER_DOCUMENTED_HELP_SUBSTRINGS,
    ISOFILTER_HELP_ARGV,
)
from pyp9m4.options.mace4 import MACE4_DOCUMENTED_HELP_SUBSTRINGS, MACE4_HELP_ARGV
from pyp9m4.options.prooftrans import (
    PROOFTRANS_DOCUMENTED_HELP_SUBSTRINGS,
    PROOFTRANS_HELP_ARGV,
)
from pyp9m4.options.prover9 import PROVER9_DOCUMENTED_HELP_SUBSTRINGS, PROVER9_HELP_ARGV
from pyp9m4.resolver import ToolName

# ``prooftrans -help`` reads stdin first; minimal Prover9 header satisfies the reader.
PROOFTRANS_HELP_STDIN: str = (
    "============================== Prover9 ===============================\n"
    "============================== end of head ===========================\n"
    "proof.\n"
)


@dataclass(frozen=True, slots=True)
class ToolCliDocSpec:
    tool: ToolName
    help_argv: tuple[str, ...]
    documented_substrings: tuple[str, ...]
    stdin: str | None = None


def iter_tool_cli_doc_specs() -> Iterator[ToolCliDocSpec]:
    yield ToolCliDocSpec("prover9", PROVER9_HELP_ARGV, PROVER9_DOCUMENTED_HELP_SUBSTRINGS)
    yield ToolCliDocSpec("mace4", MACE4_HELP_ARGV, MACE4_DOCUMENTED_HELP_SUBSTRINGS)
    yield ToolCliDocSpec(
        "interpformat", INTERPFORMAT_HELP_ARGV, INTERPFORMAT_DOCUMENTED_HELP_SUBSTRINGS
    )
    yield ToolCliDocSpec("isofilter", ISOFILTER_HELP_ARGV, ISOFILTER_DOCUMENTED_HELP_SUBSTRINGS)
    yield ToolCliDocSpec(
        "prooftrans",
        PROOFTRANS_HELP_ARGV,
        PROOFTRANS_DOCUMENTED_HELP_SUBSTRINGS,
        stdin=PROOFTRANS_HELP_STDIN,
    )
