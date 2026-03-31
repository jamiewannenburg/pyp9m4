"""CLI options for ``interpformat`` (``modelformat``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pyp9m4.options.ingest import cli_options_from_nested_dict

InterpformatStyle = Literal["standard", "standard2", "portable", "tabular", "raw", "cooked", "tex", "xml"]

INTERPFORMAT_HELP_ARGV: tuple[str, ...] = ("-help",)

INTERPFORMAT_DOCUMENTED_HELP_SUBSTRINGS: tuple[str, ...] = (
    "-f",
    "standard",
    "standard2",
    "portable",
    "tabular",
    "raw",
    "cooked",
    "tex",
    "xml",
    "output",
    "modelformat",
)


@dataclass(frozen=True, slots=True)
class InterpformatCliOptions:
    """How to print interpretations (see ``interpformat -help``)."""

    style: InterpformatStyle = "standard2"
    input_file: str | None = None
    """If set, ``-f <path>`` is passed before the style argument."""

    output_operations: str | None = None
    """Adds ``output`` and a single argument (operations spec) after the style."""

    def to_argv(self) -> list[str]:
        """Build argv fragments *after* the executable name."""
        out: list[str] = []
        if self.input_file is not None:
            out.extend(("-f", self.input_file))
        out.append(self.style)
        if self.output_operations is not None:
            out.extend(("output", self.output_operations))
        return out

    @classmethod
    def from_nested_dict(cls, data: Mapping[str, Any] | None) -> InterpformatCliOptions:
        return cli_options_from_nested_dict(cls, data)
