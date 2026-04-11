"""Hand-curated CLI option models for LADR tools and help-text alignment checks."""

from __future__ import annotations

from pyp9m4.options.ingest import (
    cli_options_from_nested_dict,
    coerce_mapping,
    unwrap_gui_value,
)
from pyp9m4.options.clausefilter import ClausefilterCliOptions
from pyp9m4.options.clausetester import ClausetesterCliOptions
from pyp9m4.options.interpfilter import InterpfilterCliOptions
from pyp9m4.options.interpformat import (
    INTERPFORMAT_DOCUMENTED_HELP_SUBSTRINGS,
    INTERPFORMAT_HELP_ARGV,
    InterpformatCliOptions,
    InterpformatStyle,
)
from pyp9m4.options.isofilter import (
    ISOFILTER_DOCUMENTED_HELP_SUBSTRINGS,
    ISOFILTER_HELP_ARGV,
    IsofilterCliOptions,
)
from pyp9m4.options.ladr_to_tptp import LadrToTptpCliOptions
from pyp9m4.options.mace4 import (
    MACE4_DOCUMENTED_HELP_SUBSTRINGS,
    MACE4_HELP_ARGV,
    Mace4CliOptions,
)
from pyp9m4.options.prooftrans import (
    PROOFTRANS_DOCUMENTED_HELP_SUBSTRINGS,
    PROOFTRANS_HELP_ARGV,
    ProofTransCliOptions,
    ProofTransMode,
)
from pyp9m4.options.prover9 import (
    PROVER9_DOCUMENTED_HELP_SUBSTRINGS,
    PROVER9_HELP_ARGV,
    Prover9CliOptions,
)
from pyp9m4.options.renamer import RenamerCliOptions
from pyp9m4.options.registry import PROOFTRANS_HELP_STDIN, iter_tool_cli_doc_specs
from pyp9m4.options.rewriter import RewriterCliOptions
from pyp9m4.options.test_clause_eval import TestClauseEvalCliOptions
from pyp9m4.options.tptp_to_ladr import TptpToLadrCliOptions
from pyp9m4.options.validate import assert_help_text_covers_tokens, fetch_tool_help_text

__all__ = [
    "cli_options_from_nested_dict",
    "coerce_mapping",
    "unwrap_gui_value",
    "ClausefilterCliOptions",
    "ClausetesterCliOptions",
    "InterpfilterCliOptions",
    "INTERPFORMAT_DOCUMENTED_HELP_SUBSTRINGS",
    "INTERPFORMAT_HELP_ARGV",
    "ISOFILTER_DOCUMENTED_HELP_SUBSTRINGS",
    "ISOFILTER_HELP_ARGV",
    "InterpformatCliOptions",
    "InterpformatStyle",
    "LadrToTptpCliOptions",
    "IsofilterCliOptions",
    "MACE4_DOCUMENTED_HELP_SUBSTRINGS",
    "MACE4_HELP_ARGV",
    "Mace4CliOptions",
    "PROOFTRANS_DOCUMENTED_HELP_SUBSTRINGS",
    "PROOFTRANS_HELP_ARGV",
    "PROOFTRANS_HELP_STDIN",
    "PROVER9_DOCUMENTED_HELP_SUBSTRINGS",
    "PROVER9_HELP_ARGV",
    "ProofTransCliOptions",
    "ProofTransMode",
    "Prover9CliOptions",
    "RenamerCliOptions",
    "RewriterCliOptions",
    "TestClauseEvalCliOptions",
    "TptpToLadrCliOptions",
    "assert_help_text_covers_tokens",
    "fetch_tool_help_text",
    "iter_tool_cli_doc_specs",
]
