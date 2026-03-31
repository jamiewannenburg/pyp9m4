"""Unified registry and :func:`arun` entry point for registered LADR tools (pipeline tools first)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pyp9m4.options.interpformat import InterpformatCliOptions
from pyp9m4.options.isofilter import IsofilterCliOptions
from pyp9m4.options.prooftrans import ProofTransCliOptions
from pyp9m4.pipeline_facades import (
    Interpformat,
    Isofilter,
    PipelineToolResult,
    Prooftrans,
)
from pyp9m4.resolver import BinaryResolver, ToolName

_TOOL_ALIASES: dict[str, ToolName] = {
    "if": "isofilter",
    "iso": "isofilter",
    "interp": "interpformat",
    "ifc": "interpformat",
    "modelformat": "interpformat",
    "pt": "prooftrans",
}

_PIPELINE_TOOL_NAMES: frozenset[ToolName] = frozenset(
    ("isofilter", "interpformat", "prooftrans")  # type: ignore[assignment]
)


def normalize_tool_name(name: str) -> ToolName:
    """Normalize user input (case, common aliases) to a :data:`~pyp9m4.resolver.ToolName` literal."""
    n = name.strip().lower()
    n = _TOOL_ALIASES.get(n, n)
    if n not in (
        "prover9",
        "mace4",
        "interpformat",
        "isofilter",
        "prooftrans",
        "clausetester",
    ):
        raise ValueError(f"unknown tool name: {name!r}")
    return n  # type: ignore[return-value]


def _as_isofilter_options(
    options: IsofilterCliOptions | Mapping[str, Any] | None,
) -> IsofilterCliOptions:
    if options is None:
        return IsofilterCliOptions()
    if isinstance(options, IsofilterCliOptions):
        return options
    if isinstance(options, Mapping):
        return IsofilterCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected IsofilterCliOptions or mapping, got {type(options).__name__}")


def _as_interpformat_options(
    options: InterpformatCliOptions | Mapping[str, Any] | None,
) -> InterpformatCliOptions:
    if options is None:
        return InterpformatCliOptions()
    if isinstance(options, InterpformatCliOptions):
        return options
    if isinstance(options, Mapping):
        return InterpformatCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected InterpformatCliOptions or mapping, got {type(options).__name__}")


def _as_prooftrans_options(
    options: ProofTransCliOptions | Mapping[str, Any] | None,
) -> ProofTransCliOptions:
    if options is None:
        return ProofTransCliOptions()
    if isinstance(options, ProofTransCliOptions):
        return options
    if isinstance(options, Mapping):
        return ProofTransCliOptions.from_nested_dict(dict(options))
    raise TypeError(f"expected ProofTransCliOptions or mapping, got {type(options).__name__}")


class ToolRegistry:
    """Maps pipeline tool names to facade instances; use :meth:`get` or :func:`arun`."""

    __slots__ = ("_interpformat", "_isofilter", "_prooftrans", "_resolver")

    def __init__(self, *, resolver: BinaryResolver | None = None) -> None:
        self._resolver = resolver or BinaryResolver()
        self._isofilter = Isofilter(resolver=self._resolver)
        self._interpformat = Interpformat(resolver=self._resolver)
        self._prooftrans = Prooftrans(resolver=self._resolver)

    @property
    def resolver(self) -> BinaryResolver:
        return self._resolver

    @property
    def isofilter(self) -> Isofilter:
        return self._isofilter

    @property
    def interpformat(self) -> Interpformat:
        return self._interpformat

    @property
    def prooftrans(self) -> Prooftrans:
        return self._prooftrans

    def get(self, program: ToolName | str) -> Isofilter | Interpformat | Prooftrans:
        """Return the facade for ``isofilter``, ``interpformat``, or ``prooftrans``."""
        name = normalize_tool_name(str(program))
        if name == "isofilter":
            return self._isofilter
        if name == "interpformat":
            return self._interpformat
        if name == "prooftrans":
            return self._prooftrans
        raise KeyError(
            f"no facade registered for {name!r} in ToolRegistry (pipeline tools: "
            f"{', '.join(sorted(_PIPELINE_TOOL_NAMES))})"
        )

    def registered_pipeline_tools(self) -> frozenset[ToolName]:
        """Tool names with facades in this registry (pipeline subset)."""
        return _PIPELINE_TOOL_NAMES


async def arun(
    program: ToolName | str,
    input: str | bytes | Path | None = None,
    *,
    options: IsofilterCliOptions
    | InterpformatCliOptions
    | ProofTransCliOptions
    | Mapping[str, Any]
    | None = None,
    resolver: BinaryResolver | None = None,
    registry: ToolRegistry | None = None,
    **kwargs: Any,
) -> PipelineToolResult:
    """Run a registered pipeline tool to completion and return :class:`~pyp9m4.pipeline_facades.PipelineToolResult`.

    Currently supports ``isofilter``, ``interpformat``, and ``prooftrans`` (including aliases, see
    :func:`normalize_tool_name`). For ``prover9`` / ``mace4``, use :class:`~pyp9m4.prover9_facade.Prover9`
    and :class:`~pyp9m4.mace4_facade.Mace4`.
    """
    reg = registry or ToolRegistry(resolver=resolver)
    name = normalize_tool_name(str(program))
    if name == "isofilter":
        opts = _as_isofilter_options(options)
        return await reg.isofilter.arun(input, options=opts, **kwargs)
    if name == "interpformat":
        opts = _as_interpformat_options(options)
        return await reg.interpformat.arun(input, options=opts, **kwargs)
    if name == "prooftrans":
        opts = _as_prooftrans_options(options)
        return await reg.prooftrans.arun(input, options=opts, **kwargs)
    raise ValueError(
        f"arun() does not dispatch {name!r}; use Prover9 or Mace4 facades for prover9/mace4, "
        "or a direct SubprocessInvocation for other tools."
    )
