"""Domain parsers for Prover9, Mace4, and pipeline tools."""

from pyp9m4.parsers.common import ParseWarning, match_section_title_line, parse_equals_key_values, split_ladr_section_blocks
from pyp9m4.parsers.mace4 import (
    Mace4Interpretation,
    Mace4InterpretationBuffer,
    Mace4Parsed,
    Mace4StdoutMetadata,
    StandardAssignment,
    domain_size_from_mace4_section_title,
    extract_interpretation_blocks,
    format_mace4_interpretation,
    mace4_interpretations_only_stdout,
    parse_mace4_output,
    parse_mace4_stdout_metadata,
)
from pyp9m4.parsers.pipeline import (
    PipelineTextInspection,
    PipelineTextResult,
    inspect_pipeline_text,
    parse_pipeline_tool_output,
)
from pyp9m4.parsers.prover9 import ProofSegment, Prover9Parsed, parse_prover9_output
from pyp9m4.parsers.prover9_outcome import ProverOutcome, infer_prover_outcome

Interpretation = Mace4Interpretation
Model = Interpretation

__all__ = [
    "Interpretation",
    "Model",
    "Mace4Interpretation",
    "Mace4InterpretationBuffer",
    "Mace4Parsed",
    "Mace4StdoutMetadata",
    "ParseWarning",
    "PipelineTextInspection",
    "PipelineTextResult",
    "ProofSegment",
    "Prover9Parsed",
    "ProverOutcome",
    "infer_prover_outcome",
    "StandardAssignment",
    "domain_size_from_mace4_section_title",
    "extract_interpretation_blocks",
    "format_mace4_interpretation",
    "mace4_interpretations_only_stdout",
    "inspect_pipeline_text",
    "match_section_title_line",
    "parse_equals_key_values",
    "parse_mace4_output",
    "parse_mace4_stdout_metadata",
    "parse_pipeline_tool_output",
    "parse_prover9_output",
    "split_ladr_section_blocks",
]
