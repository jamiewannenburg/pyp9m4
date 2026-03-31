"""CLI options for ``isofilter``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pyp9m4.options.ingest import cli_options_from_nested_dict

ISOFILTER_HELP_ARGV: tuple[str, ...] = ("-help",)

ISOFILTER_DOCUMENTED_HELP_SUBSTRINGS: tuple[str, ...] = (
    "ignore_constants",
    "wrap",
    "check",
    "output",
    "discrim",
    "isofilter",
)


@dataclass(frozen=True, slots=True)
class IsofilterCliOptions:
    """Optional arguments accepted after the executable name (see ``isofilter -help``)."""

    ignore_constants: bool = False
    wrap: bool = False
    check_operations: str | None = None
    output_operations: str | None = None
    discrim_path: str | None = None

    def to_argv(self) -> list[str]:
        """Build argv fragments *after* the executable name."""
        out: list[str] = []
        if self.ignore_constants:
            out.append("ignore_constants")
        if self.wrap:
            out.append("wrap")
        if self.check_operations is not None:
            out.extend(("check", self.check_operations))
        if self.output_operations is not None:
            out.extend(("output", self.output_operations))
        if self.discrim_path is not None:
            out.extend(("discrim", self.discrim_path))
        return out

    @classmethod
    def from_nested_dict(cls, data: Mapping[str, Any] | None) -> IsofilterCliOptions:
        return cli_options_from_nested_dict(cls, data)
