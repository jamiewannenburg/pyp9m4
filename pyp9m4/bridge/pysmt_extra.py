"""Optional PySMT bridge: install with ``pip install pyp9m4[smt]``."""

from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import Any


def _require_pysmt() -> None:
    try:
        import pysmt  # noqa: F401 — presence check
    except ImportError as e:  # pragma: no cover - exercised when extra missing
        raise ImportError(
            "PySMT is not installed. Install the optional dependency with: pip install pyp9m4[smt]"
        ) from e


def is_pysmt_available() -> bool:
    """Return True if PySMT can be imported (``smt`` extra installed)."""
    try:
        import pysmt  # noqa: F401

        return True
    except ImportError:
        return False


def read_smtlib_script_as_formulas(path: Path | str) -> Sequence[Any]:
    """Parse *path* with PySMT's SMT-LIB frontend and return asserted formula objects.

    Returns one PySMT formula per ``assert`` command (empty if none).
    """
    _require_pysmt()
    from pysmt.smtlib.parser import SmtLibParser
    from pysmt.smtlib.script import SmtLibCommand

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    parser = SmtLibParser()
    script = parser.get_script(StringIO(text))
    out: list[Any] = []
    for cmd in script.commands:
        if isinstance(cmd, SmtLibCommand) and cmd.name == "assert":
            out.extend(cmd.args)
    return out


def parse_smtlib_string(script: str) -> Any:
    """Parse a full SMT-LIB script string using PySMT (returns a :class:`pysmt.smtlib.script.SmtLibScript`)."""
    _require_pysmt()
    from pysmt.smtlib.parser import SmtLibParser

    parser = SmtLibParser()
    return parser.get_script(StringIO(script))
