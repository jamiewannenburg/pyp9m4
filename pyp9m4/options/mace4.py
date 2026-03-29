"""CLI options for ``mace4`` (finite model search)."""

from __future__ import annotations

from dataclasses import dataclass

# LADR prints full usage for ``mace4 -help`` (single-dash; ``--help`` is rejected).
MACE4_HELP_ARGV: tuple[str, ...] = ("-help",)

MACE4_DOCUMENTED_HELP_SUBSTRINGS: tuple[str, ...] = (
    "-n",
    "-N",
    "-i",
    "-P",
    "-p",
    "-m",
    "-t",
    "-s",
    "-b",
    "-V",
    "-v",
    "-L",
    "-O",
    "-M",
    "-G",
    "-H",
    "-I",
    "-J",
    "-K",
    "-T",
    "-R",
    "-q",
    "-S",
    "-c",
    "mace4",
    "domain_size",
)


@dataclass(frozen=True, slots=True)
class Mace4CliOptions:
    """Command-line overrides for Mace4 parms/flags (each takes a value except ``-c``).

    For boolean parms, pass ``0`` or ``1`` as documented by the binary.
    """

    domain_size: int | None = None
    end_size: int | None = None
    increment: int | None = None
    print_models: int | None = None
    print_models_tabular: int | None = None
    max_models: int | None = None
    max_seconds: int | None = None
    max_seconds_per: int | None = None
    max_megs: int | None = None
    prolog_style_variables: int | None = None
    verbose: int | None = None
    lnh: int | None = None
    selection_order: int | None = None
    selection_measure: int | None = None
    negprop: int | None = None
    neg_assign: int | None = None
    neg_assign_near: int | None = None
    neg_elim: int | None = None
    neg_elim_near: int | None = None
    trace: int | None = None
    integer_ring: int | None = None
    iterate_primes: int | None = None
    skolems_last: int | None = None
    ignore_unrecognized_assigns: bool = False
    """``-c`` — ignore unrecognized ``set``/``clear``/``assign`` in the input file."""

    def to_argv(self) -> list[str]:
        """Build argv fragments *after* the executable name."""
        pairs: list[tuple[str, int]] = []
        if self.domain_size is not None:
            pairs.append(("-n", self.domain_size))
        if self.end_size is not None:
            pairs.append(("-N", self.end_size))
        if self.increment is not None:
            pairs.append(("-i", self.increment))
        if self.print_models is not None:
            pairs.append(("-P", self.print_models))
        if self.print_models_tabular is not None:
            pairs.append(("-p", self.print_models_tabular))
        if self.max_models is not None:
            pairs.append(("-m", self.max_models))
        if self.max_seconds is not None:
            pairs.append(("-t", self.max_seconds))
        if self.max_seconds_per is not None:
            pairs.append(("-s", self.max_seconds_per))
        if self.max_megs is not None:
            pairs.append(("-b", self.max_megs))
        if self.prolog_style_variables is not None:
            pairs.append(("-V", self.prolog_style_variables))
        if self.verbose is not None:
            pairs.append(("-v", self.verbose))
        if self.lnh is not None:
            pairs.append(("-L", self.lnh))
        if self.selection_order is not None:
            pairs.append(("-O", self.selection_order))
        if self.selection_measure is not None:
            pairs.append(("-M", self.selection_measure))
        if self.negprop is not None:
            pairs.append(("-G", self.negprop))
        if self.neg_assign is not None:
            pairs.append(("-H", self.neg_assign))
        if self.neg_assign_near is not None:
            pairs.append(("-I", self.neg_assign_near))
        if self.neg_elim is not None:
            pairs.append(("-J", self.neg_elim))
        if self.neg_elim_near is not None:
            pairs.append(("-K", self.neg_elim_near))
        if self.trace is not None:
            pairs.append(("-T", self.trace))
        if self.integer_ring is not None:
            pairs.append(("-R", self.integer_ring))
        if self.iterate_primes is not None:
            pairs.append(("-q", self.iterate_primes))
        if self.skolems_last is not None:
            pairs.append(("-S", self.skolems_last))

        out: list[str] = []
        for flag, val in pairs:
            out.extend((flag, str(val)))
        if self.ignore_unrecognized_assigns:
            out.append("-c")
        return out
