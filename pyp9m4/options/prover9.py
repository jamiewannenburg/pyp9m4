"""CLI options for ``prover9`` (McCune/LADR)."""

from __future__ import annotations

from dataclasses import dataclass

# ``prover9 -h`` / ``prover9 --help`` prints usage; ``-h`` is what the usage line documents.
PROVER9_HELP_ARGV: tuple[str, ...] = ("-h",)

PROVER9_DOCUMENTED_HELP_SUBSTRINGS: tuple[str, ...] = (
    "-h",
    "-x",
    "-p",
    "-t",
    "-f",
    "usage:",
    "prover9",
)


@dataclass(frozen=True, slots=True)
class Prover9CliOptions:
    """Command-line switches documented in ``prover9 -h``.

    Other parameters are set in the input stream (``set``/``clear``/``assign``).
    """

    auto2: bool = False
    """``-x`` — equivalent to ``set(auto2)``."""

    parenthesize_output: bool = False
    """``-p`` — fully parenthesize output."""

    max_seconds: int | None = None
    """``-t n`` — ``assign(max_seconds, n)`` (overrides input file)."""

    input_files: tuple[str, ...] = ()
    """``-f`` followed by file paths (stdin is used when empty)."""

    def to_argv(self) -> list[str]:
        """Build argv fragments *after* the executable name."""
        out: list[str] = []
        if self.auto2:
            out.append("-x")
        if self.parenthesize_output:
            out.append("-p")
        if self.max_seconds is not None:
            out.extend(("-t", str(self.max_seconds)))
        if self.input_files:
            out.append("-f")
            out.extend(self.input_files)
        return out
