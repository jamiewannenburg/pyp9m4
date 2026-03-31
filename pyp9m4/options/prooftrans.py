"""CLI options for ``prooftrans``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pyp9m4.options.ingest import cli_options_from_nested_dict

ProofTransMode = Literal["default", "parents_only", "xml", "ivy", "hints", "tagged"]

PROOFTRANS_HELP_ARGV: tuple[str, ...] = ("-help",)

PROOFTRANS_DOCUMENTED_HELP_SUBSTRINGS: tuple[str, ...] = (
    "prooftrans",
    "parents_only",
    "xml",
    "ivy",
    "hints",
    "tagged",
    "expand",
    "renumber",
    "striplabels",
    "-f",
    "-label",
)


@dataclass(frozen=True, slots=True)
class ProofTransCliOptions:
    """Transform Prover9 proof output (see ``prooftrans -help`` with stdin proof text)."""

    mode: ProofTransMode = "default"
    expand: bool = False
    renumber: bool = False
    striplabels: bool = False
    label: str | None = None
    """For ``hints`` mode: ``-label <label>``."""

    input_file: str | None = None
    """``-f`` path (passed after mode/flags)."""

    def to_argv(self) -> list[str]:
        """Build argv fragments *after* the executable name."""
        out: list[str] = []
        if self.mode != "default":
            out.append(
                {
                    "parents_only": "parents_only",
                    "xml": "xml",
                    "ivy": "ivy",
                    "hints": "hints",
                    "tagged": "tagged",
                }[self.mode]
            )
        if self.mode == "hints" and self.label is not None:
            out.extend(("-label", self.label))
        if self.expand:
            out.append("expand")
        if self.renumber:
            out.append("renumber")
        if self.striplabels:
            out.append("striplabels")
        if self.input_file is not None:
            out.extend(("-f", self.input_file))
        return out

    @classmethod
    def from_nested_dict(cls, data: Mapping[str, Any] | None) -> ProofTransCliOptions:
        return cli_options_from_nested_dict(cls, data)
