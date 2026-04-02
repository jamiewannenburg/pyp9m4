"""Parse Mace4 model output: ``interpretation(...)`` blocks and standard assignments."""

from __future__ import annotations

import ast
import html
import os
import re
import tempfile
from itertools import product
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyp9m4.parsers.common import ParseWarning, split_ladr_section_blocks
from pyp9m4.resolver import BinaryResolver
from pyp9m4.runner import SubprocessInvocation, ToolRunResult, run_sync


_INTERP_NEEDLE = "interpretation("
_LEN_INTERP_BEFORE_LPAREN = len("interpretation")


def _matching_close_paren(s: str, open_paren_idx: int) -> int | None:
    """Index of the ``)`` matching ``(`` at ``open_paren_idx``, or ``None`` if EOF leaves unclosed parens."""
    assert s[open_paren_idx] == "("
    depth = 0
    i = open_paren_idx
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _try_extract_next_interpretation(s: str, pos: int = 0) -> tuple[str, int] | None:
    """Next complete ``interpretation(...)`` starting at or after ``pos``, or ``None`` if none is complete yet."""
    while True:
        i = s.find(_INTERP_NEEDLE, pos)
        if i < 0:
            return None
        open_paren = i + _LEN_INTERP_BEFORE_LPAREN
        if open_paren >= len(s) or s[open_paren] != "(":
            pos = i + 1
            continue
        close = _matching_close_paren(s, open_paren)
        if close is None:
            return None
        end = close + 1
        # LADR term reader expects a terminating period after the interpretation term.
        # Mace4 prints it as `interpretation(...).`, but our balanced-paren scan would
        # otherwise stop at `)` and drop the dot.
        if end < len(s) and s[end] == ".":
            end += 1
        return (s[i:end], end)


def extract_interpretation_blocks(text: str) -> tuple[str, ...]:
    """Return each complete ``interpretation(...)`` term substring.

    If Mace4 printed a terminating period (i.e. `interpretation(...).`), include it too.

    Only balanced blocks are returned; a trailing incomplete ``interpretation(``… is ignored
    until closed (e.g. when using :class:`Mace4InterpretationBuffer` across chunks).
    """
    out: list[str] = []
    pos = 0
    while True:
        got = _try_extract_next_interpretation(text, pos)
        if got is None:
            break
        block, pos = got
        out.append(block)
    return tuple(out)


_DOMAIN_RE = re.compile(r"interpretation\s*\(\s*(\d+)\s*,")
_ASSIGN_LINE_RE = re.compile(
    r"^\s*(function|relation)\s*=\s*(.+?)\s*,?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StandardAssignment:
    """One line in Mace4 standard / standard2 structure output."""

    kind: str
    """``function`` or ``relation`` (lowercase)."""

    rhs: str
    """Right-hand side after ``=`` (trimmed)."""


def _split_lhs_value(rhs: str) -> tuple[str, int] | None:
    """Split ``lhs = value`` on the last ``=``; return ``(lhs, int_value)`` or ``None``."""
    rhs = rhs.strip()
    idx = rhs.rfind("=")
    if idx < 0:
        return None
    lhs, val_s = rhs[:idx].strip(), rhs[idx + 1 :].strip()
    try:
        v = int(val_s)
    except ValueError:
        return None
    return lhs, v


def _split_args_depth0(inner: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, c in enumerate(inner):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(inner[start:i].strip())
            start = i + 1
    parts.append(inner[start:].strip())
    return [p for p in parts if p]


def _parse_domain_arg(token: str) -> int:
    t = token.strip()
    if t.startswith("(") and t.endswith(")"):
        inner = t[1:-1].strip()
        try:
            return int(inner)
        except ValueError as e:
            raise ValueError(f"bad parenthesized arg {token!r}") from e
    return int(t)


def _parse_assignment_lhs(lhs: str) -> tuple[str, tuple[int, ...]] | None:
    """Return ``(symbol, args)`` for constants ``sym`` (empty args) or ``sym(a,b,...)``."""
    lhs = lhs.strip()
    if not lhs:
        return None
    p = lhs.find("(")
    if p < 0:
        return lhs, ()
    if not lhs.endswith(")"):
        return None
    name = lhs[:p].strip()
    if not name:
        return None
    inner = lhs[p + 1 : -1]
    try:
        args = tuple(_parse_domain_arg(x) for x in _split_args_depth0(inner))
    except ValueError:
        return None
    return name, args


def _parse_standard_rhs(
    kind: str, rhs: str
) -> tuple[str, tuple[int, ...], int, bool] | None:
    """Parse one assignment rhs into ``(name, args, value, is_relation)`` or ``None``."""
    sp = _split_lhs_value(rhs)
    if sp is None:
        return None
    lhs, val = sp
    parsed = _parse_assignment_lhs(lhs)
    if parsed is None:
        return None
    name, args = parsed
    is_relation = kind == "relation"
    return name, args, val, is_relation


def _build_interpretation_tables(
    assigns: tuple[StandardAssignment, ...],
) -> tuple[
    tuple[tuple[str, tuple[int, ...], int], ...],
    tuple[tuple[str, tuple[int, ...], bool], ...],
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    tuple[ParseWarning, ...],
]:
    fn_rows: list[tuple[str, tuple[int, ...], int]] = []
    rel_rows: list[tuple[str, tuple[int, ...], bool]] = []
    fn_arity: dict[str, int] = {}
    rel_arity: dict[str, int] = {}
    warns: list[ParseWarning] = []

    for a in assigns:
        row = _parse_standard_rhs(a.kind, a.rhs)
        if row is None:
            warns.append(
                ParseWarning(
                    "assignment_parse_failed",
                    f"could not parse {a.kind} assignment: {a.rhs!r}",
                )
            )
            continue
        name, args, val, is_relation = row
        arity = len(args)
        if is_relation:
            prev = rel_arity.get(name)
            if prev is not None and prev != arity:
                warns.append(
                    ParseWarning(
                        "relation_arity_mismatch",
                        f"relation {name!r}: arity {prev} vs {arity}",
                    )
                )
            else:
                rel_arity[name] = arity
            rel_rows.append((name, args, val != 0))
        else:
            prev = fn_arity.get(name)
            if prev is not None and prev != arity:
                warns.append(
                    ParseWarning(
                        "function_arity_mismatch",
                        f"function {name!r}: arity {prev} vs {arity}",
                    )
                )
            else:
                fn_arity[name] = arity
            fn_rows.append((name, args, val))

    fn_rows.sort(key=lambda t: (t[0], t[1]))
    rel_rows.sort(key=lambda t: (t[0], t[1]))
    fn_ar_t = tuple(sorted(fn_arity.items()))
    rel_ar_t = tuple(sorted(rel_arity.items()))
    return (
        tuple(fn_rows),
        tuple(rel_rows),
        fn_ar_t,
        rel_ar_t,
        tuple(warns),
    )


def _split_top_level_commas(s: str) -> list[str]:
    """Split on commas not inside (), or [].

    Used for parsing list-style Mace4 terms like:
    - function(sym, [0,1,...])
    - relation(P(_,_), [1,0,...])
    """
    parts: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    start = 0
    for i, c in enumerate(s):
        if c == "(":
            paren_depth += 1
        elif c == ")":
            paren_depth -= 1
        elif c == "[":
            bracket_depth += 1
        elif c == "]":
            bracket_depth -= 1
        elif c == "," and paren_depth == 0 and bracket_depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return [p for p in parts if p]


_INT_RE = re.compile(r"-?\d+")


def _parse_int_list(list_s: str) -> list[int] | None:
    s = list_s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    inner = s[1:-1].strip()
    return [int(x) for x in _INT_RE.findall(inner)]


def _extract_function_and_relation_terms(block: str, keyword: str) -> list[str]:
    """Extract top-level `keyword(...)` terms from a balanced `interpretation(...)` block."""
    out: list[str] = []
    # The keyword may have spaces before the '('.
    pat = re.compile(rf"\b{re.escape(keyword)}\s*\(")
    for m in pat.finditer(block):
        open_paren_idx = m.end() - 1
        close = _matching_close_paren(block, open_paren_idx)
        if close is None:
            continue
        out.append(block[m.start() : close + 1])
    return out


def _infer_arity_from_list_len(domain_size: int, values_len: int) -> int | None:
    """Infer arity `k` where `domain_size**k == values_len`."""
    if values_len == 1:
        return 0
    if domain_size <= 0:
        return None
    p = 1
    k = 0
    while p < values_len:
        p *= domain_size
        k += 1
        if k > 6:  # keep this parse bounded for weird data
            break
    return k if p == values_len else None


def _build_tables_from_list_style(
    block: str,
    *,
    domain_size: int | None,
) -> tuple[
    tuple[tuple[str, tuple[int, ...], int], ...],
    tuple[tuple[str, tuple[int, ...], bool], ...],
    tuple[ParseWarning, ...],
]:
    """Parse list-style Mace4 model output into the same table shapes.

    Supported shapes:
    - `function(sym, [v0, v1, ...])`
    - `relation(P(_,_), [b0, b1, ...])`
    """
    warns: list[ParseWarning] = []
    fn_map: dict[tuple[str, tuple[int, ...]], int] = {}
    fn_arity: dict[str, int] = {}
    rel_map: dict[tuple[str, tuple[int, ...]], bool] = {}
    rel_arity: dict[str, int] = {}

    # function(sym, [..])
    for term in _extract_function_and_relation_terms(block, "function"):
        open_i = term.find("(")
        inner = term[open_i + 1 : -1].strip()
        parts = _split_top_level_commas(inner)
        if len(parts) != 2:
            warns.append(ParseWarning("function_term_parse_failed", f"could not split {term!r}"))
            continue
        sym = parts[0].strip()
        vals = _parse_int_list(parts[1])
        if vals is None:
            warns.append(ParseWarning("function_values_parse_failed", f"could not parse list in {term!r}"))
            continue

        if domain_size is None:
            if len(vals) == 1:
                arity = 0
            else:
                warns.append(
                    ParseWarning(
                        "function_arity_infer_failed",
                        f"domain_size missing; cannot infer arity for {sym!r} (len={len(vals)})",
                    )
                )
                continue
        else:
            arity = _infer_arity_from_list_len(domain_size, len(vals))
            if arity is None:
                warns.append(
                    ParseWarning(
                        "function_arity_infer_failed",
                        f"cannot infer arity for {sym!r} with domain_size={domain_size} and len(values)={len(vals)}",
                    )
                )
                continue

        if arity == 0:
            key = (sym, ())
            fn_map[key] = vals[0]
            prev = fn_arity.get(sym)
            if prev is not None and prev != 0:
                warns.append(
                    ParseWarning(
                        "function_arity_mismatch",
                        f"function {sym!r}: arity {prev} vs 0",
                    )
                )
            fn_arity[sym] = 0
            continue

        d = domain_size
        expected = d**arity
        if len(vals) != expected:
            warns.append(
                ParseWarning(
                    "function_values_length_mismatch",
                    f"function {sym!r}: expected {expected} values for arity {arity} but got {len(vals)}",
                )
            )
            continue

        for idx, args in enumerate(product(range(d), repeat=arity)):
            fn_map[(sym, args)] = vals[idx]
        fn_arity[sym] = arity

    # relation(P(_,_), [..])
    for term in _extract_function_and_relation_terms(block, "relation"):
        open_i = term.find("(")
        inner = term[open_i + 1 : -1].strip()
        parts = _split_top_level_commas(inner)
        if len(parts) != 2:
            warns.append(ParseWarning("relation_term_parse_failed", f"could not split {term!r}"))
            continue
        template = parts[0].strip()
        vals = _parse_int_list(parts[1])
        if vals is None:
            warns.append(ParseWarning("relation_values_parse_failed", f"could not parse list in {term!r}"))
            continue

        # Parse template: `P(_)`, `P(_,_ )`, etc.
        tpl_open = template.find("(")
        if tpl_open < 0:
            rel_name = template
            rel_k = 0
        else:
            rel_name = template[:tpl_open].strip()
            tpl_inner = template[tpl_open + 1 : -1].strip()
            if not tpl_inner:
                rel_k = 0
            else:
                toks = [t.strip() for t in tpl_inner.split(",") if t.strip()]
                rel_k = len(toks)
                if any(t != "_" for t in toks):
                    warns.append(
                        ParseWarning(
                            "relation_template_unexpected",
                            f"expected '_' placeholders in {template!r} but got {toks!r}",
                        )
                    )

        if domain_size is None:
            warns.append(
                ParseWarning(
                    "relation_arity_infer_failed",
                    f"domain_size missing; cannot infer relation {rel_name!r} entries",
                )
            )
            continue

        d = domain_size
        expected = d**rel_k
        if len(vals) != expected:
            warns.append(
                ParseWarning(
                    "relation_values_length_mismatch",
                    f"relation {rel_name!r}: expected {expected} values for arity {rel_k} but got {len(vals)}",
                )
            )
            continue

        if rel_k == 0:
            rel_map[(rel_name, ())] = vals[0] != 0
            rel_arity[rel_name] = 0
            continue

        for idx, args in enumerate(product(range(d), repeat=rel_k)):
            rel_map[(rel_name, args)] = vals[idx] != 0
        rel_arity[rel_name] = rel_k

    fn_entries = sorted(((n, args, v) for (n, args), v in fn_map.items()), key=lambda x: (x[0], x[1]))
    rel_entries = sorted(((n, args, v) for (n, args), v in rel_map.items()), key=lambda x: (x[0], x[1]))
    fn_ar_t = tuple(sorted(fn_arity.items()))
    rel_ar_t = tuple(sorted(rel_arity.items()))

    return (
        tuple(fn_entries),
        tuple(rel_entries),
        tuple(warns),
    )


@dataclass(frozen=True, slots=True)
class Mace4Interpretation:
    """One extracted model with queryable function/relation tables (standard format)."""

    raw: str
    domain_size: int | None
    standard_assignments: tuple[StandardAssignment, ...]
    function_entries: tuple[tuple[str, tuple[int, ...], int], ...]
    relation_entries: tuple[tuple[str, tuple[int, ...], bool], ...]
    function_arities: tuple[tuple[str, int], ...]
    relation_arities: tuple[tuple[str, int], ...]

    def _functions_map(self) -> dict[str, int]:
        return dict(self.function_arities)

    def _relations_map(self) -> dict[str, int]:
        return dict(self.relation_arities)

    def _fn_lookup(self) -> dict[tuple[str, tuple[int, ...]], int]:
        return {(n, a): v for n, a, v in self.function_entries}

    def _rel_lookup(self) -> dict[tuple[str, tuple[int, ...]], bool]:
        return {(n, a): v for n, a, v in self.relation_entries}

    @property
    def functions(self) -> Mapping[str, int]:
        """Map each function symbol to its arity."""
        return self._functions_map()

    @property
    def relations(self) -> Mapping[str, int]:
        """Map each relation symbol to its arity."""
        return self._relations_map()

    @property
    def function_symbols(self) -> tuple[str, ...]:
        return tuple(n for n, _ in self.function_arities)

    @property
    def relation_symbols(self) -> tuple[str, ...]:
        return tuple(n for n, _ in self.relation_arities)

    def _check_domain_and_arity(
        self, kind: str, symbol: str, args: tuple[int, ...], expected_kind: str
    ) -> None:
        if self.domain_size is None:
            raise KeyError("domain_size is unknown; cannot evaluate")
        d = self.domain_size
        for x in args:
            if x < 0 or x >= d:
                raise KeyError(f"argument {x} out of domain [0, {d})")
        arities = self._relations_map() if expected_kind == "relation" else self._functions_map()
        if symbol not in arities:
            raise KeyError(f"unknown {expected_kind} symbol {symbol!r}")
        if len(args) != arities[symbol]:
            raise KeyError(
                f"{symbol!r} has arity {arities[symbol]}, got {len(args)} arguments"
            )

    def holds(self, relation: str, *args: int) -> bool:
        """True iff the relation holds on ``args`` (integers in ``[0, domain_size)``)."""
        t = tuple(args)
        self._check_domain_and_arity("relation", relation, t, "relation")
        key = (relation, t)
        lk = self._rel_lookup()
        if key not in lk:
            raise KeyError(f"no value for relation {relation}{t}")
        return lk[key]

    def value_at(self, function: str, *args: int) -> int:
        """Value of ``function`` at ``args``."""
        t = tuple(args)
        self._check_domain_and_arity("function", function, t, "function")
        key = (function, t)
        lk = self._fn_lookup()
        if key not in lk:
            raise KeyError(f"no value for function {function}{t}")
        return lk[key]

    def get_value(self, function: str, *args: int) -> int:
        """Alias of :meth:`value_at` (SMT-style “read value from model” naming)."""
        return self.value_at(function, *args)

    def model_eval(self, function: str, *args: int) -> int:
        """Alias of :meth:`value_at` (avoids a method named ``eval``, which would shadow :func:`eval`)."""
        return self.value_at(function, *args)

    def as_relation(self, name: str) -> Callable[..., bool]:
        """Callable taking ``arity`` domain integers; same as :meth:`holds`."""
        if name not in self._relations_map():
            raise KeyError(f"unknown relation {name!r}")
        arity = self._relations_map()[name]

        def _rel(*xs: int) -> bool:
            if len(xs) != arity:
                raise TypeError(f"{name!r} expects {arity} arguments, got {len(xs)}")
            return self.holds(name, *xs)

        return _rel

    def as_function(self, name: str) -> Callable[..., int]:
        """Callable taking ``arity`` domain integers; same as :meth:`value_at`."""
        if name not in self._functions_map():
            raise KeyError(f"unknown function {name!r}")
        arity = self._functions_map()[name]

        def _fn(*xs: int) -> int:
            if len(xs) != arity:
                raise TypeError(f"{name!r} expects {arity} arguments, got {len(xs)}")
            return self.value_at(name, *xs)

        return _fn

    def iter_relation_tuples(self, name: str) -> Iterator[tuple[tuple[int, ...], bool]]:
        """Yield ``(args, holds)`` for every tuple listed for relation ``name``."""
        for n, args, val in self.relation_entries:
            if n == name:
                yield args, val

    def iter_function_entries(self, name: str) -> Iterator[tuple[tuple[int, ...], int]]:
        """Yield ``(args, value)`` for every row listed for function ``name``."""
        for n, args, val in self.function_entries:
            if n == name:
                yield args, val

    def format_tables(self, *, max_arity3_rows: int = 64) -> str:
        """Plain-text tables (same body as :meth:`__str__` without header line)."""
        return _format_interpretation_tables(self, max_arity3_rows=max_arity3_rows)

    def __repr__(self) -> str:
        return (
            f"Mace4Interpretation(domain_size={self.domain_size!r}, "
            f"functions={len(self.function_arities)}, relations={len(self.relation_arities)})"
        )

    def __str__(self) -> str:
        parts = [
            f"Mace4Interpretation(domain_size={self.domain_size})",
            self.format_tables(),
        ]
        return "\n".join(parts)

    def _repr_html_(self) -> str:
        return _html_interpretation_tables(self)

    def _repr_pretty_(self, p: Any, cycle: bool) -> None:
        if cycle:
            p.text("Mace4Interpretation(...)")
            return
        p.text(str(self))

    def test_clause(
        self,
        clause: str,
        *,
        resolver: BinaryResolver | None = None,
        clausetester_executable: Path | str | None = None,
        cwd: Path | str | None = None,
        timeout_s: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ToolRunResult:
        """Run ``clausetester`` on this interpretation (temp file) with ``clause`` on stdin.

        LADR expects: ``clausetester <interp_file> < <clauses_stream>``. A trailing ``.`` is
        appended to the interpretation text when missing (required by the LADR term reader).
        """
        exe = (
            Path(clausetester_executable)
            if clausetester_executable is not None
            else (resolver or BinaryResolver()).resolve("clausetester")
        )
        # LADR's reader expects a terminating period after the interpretation term.
        body = self.raw.rstrip()
        if not body.endswith("."):
            body = body + "."
        data = body + "\n"
        tmp_path: Path | None = None
        try:
            fd, tmp_path_str = tempfile.mkstemp(suffix=".interp", prefix="pyp9m4_")
            tmp_path = Path(tmp_path_str)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
            inv = SubprocessInvocation(
                argv=(str(exe), str(tmp_path)),
                cwd=cwd,
                env=env,
                stdin=clause if clause.endswith("\n") else clause + "\n",
                timeout_s=timeout_s,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return run_sync(inv)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _format_interpretation_tables(mi: Mace4Interpretation, *, max_arity3_rows: int) -> str:
    lines: list[str] = []
    d = mi.domain_size

    def sym_line(title: str, arities: tuple[tuple[str, int], ...]) -> None:
        if not arities:
            lines.append(f"  ({title}: none)")
            return
        bits = [f"{n}/{a}" for n, a in arities]
        lines.append(f"  {title}: " + ", ".join(bits))

    sym_line("Functions", mi.function_arities)
    sym_line("Relations", mi.relation_arities)
    lines.append("")

    by_fn: dict[str, list[tuple[tuple[int, ...], int]]] = {}
    for n, args, v in mi.function_entries:
        by_fn.setdefault(n, []).append((args, v))
    for name in sorted(by_fn.keys()):
        rows = sorted(by_fn[name], key=lambda x: x[0])
        ar = mi._functions_map()[name]
        lines.append(f"  [{name}] arity {ar}")
        if ar == 0:
            lines.append(f"    -> {rows[0][1]}")
        elif ar == 1 and d is not None:
            w = max(3, len(str(d - 1)), len(str(max(v for _, v in rows))))
            header = " " * 4 + " ".join(f"{i:>{w}}" for i in range(d))
            line = " " * 4 + " ".join(f"{dict(rows).get((i,), '-'):>{w}}" for i in range(d))
            lines.append(header)
            lines.append(line)
        elif ar == 2 and d is not None:
            w = max(3, len(str(d - 1)), len(str(max(v for _, v in rows))))
            top = " " * (w + 2) + " ".join(f"{j:>{w}}" for j in range(d))
            lines.append(top)
            grid = {(a[0], a[1]): v for a, v in rows if len(a) == 2}
            for i in range(d):
                row_bits = [f"{grid.get((i, j), '-'):>{w}}" for j in range(d)]
                lines.append(f"  {i:>{w}} | " + " ".join(row_bits))
        else:
            nshow = 0
            for args, v in rows:
                if ar >= 3 and nshow >= max_arity3_rows:
                    lines.append(f"    ... ({len(rows) - nshow} more)")
                    break
                lines.append(f"    {args} -> {v}")
                nshow += 1
        lines.append("")

    by_rel: dict[str, list[tuple[tuple[int, ...], bool]]] = {}
    for n, args, v in mi.relation_entries:
        by_rel.setdefault(n, []).append((args, v))
    for name in sorted(by_rel.keys()):
        rows = sorted(by_rel[name], key=lambda x: x[0])
        ar = mi._relations_map()[name]
        lines.append(f"  [{name}] arity {ar}")
        if ar == 0:
            lines.append(f"    -> {rows[0][1]}")
        elif ar == 1 and d is not None:
            w = 3
            header = " " * 4 + " ".join(f"{i:>{w}}" for i in range(d))
            tf = {i: ("T" if dict(rows).get((i,), False) else "F") for i in range(d)}
            line = " " * 4 + " ".join(f"{tf[i]:>{w}}" for i in range(d))
            lines.append(header)
            lines.append(line)
        elif ar == 2 and d is not None:
            w = 3
            top = " " * (w + 2) + " ".join(f"{j:>{w}}" for j in range(d))
            lines.append(top)
            grid = {(a[0], a[1]): v for a, v in rows if len(a) == 2}
            for i in range(d):
                row_bits2 = []
                for j in range(d):
                    if (i, j) in grid:
                        row_bits2.append("T" if grid[(i, j)] else "F")
                    else:
                        row_bits2.append("-")
                lines.append(f"  {i:>{w}} | " + " ".join(f"{x:>{w}}" for x in row_bits2))
        else:
            nshow = 0
            for args, v in rows:
                if ar >= 3 and nshow >= max_arity3_rows:
                    lines.append(f"    ... ({len(rows) - nshow} more)")
                    break
                lines.append(f"    {args} -> {v}")
                nshow += 1
        lines.append("")

    return "\n".join(lines).rstrip()


def _html_interpretation_tables(mi: Mace4Interpretation) -> str:
    esc = html.escape
    chunks: list[str] = [
        f"<div class='pyp9m4-mace4interp'><p><b>Mace4Interpretation</b> "
        f"domain_size={esc(str(mi.domain_size))}</p>"
    ]
    chunks.append("<p><b>Functions</b> " + esc(", ".join(f"{n}/{a}" for n, a in mi.function_arities)) + "</p>")
    chunks.append("<p><b>Relations</b> " + esc(", ".join(f"{n}/{a}" for n, a in mi.relation_arities)) + "</p>")

    d = mi.domain_size

    by_fn: dict[str, list[tuple[tuple[int, ...], int]]] = {}
    for n, args, v in mi.function_entries:
        by_fn.setdefault(n, []).append((args, v))
    for name in sorted(by_fn.keys()):
        rows = sorted(by_fn[name], key=lambda x: x[0])
        ar = mi._functions_map()[name]
        chunks.append(f"<h4>{esc(name)} <small>(function, arity {ar})</small></h4>")
        if ar == 0:
            chunks.append(f"<p>{esc(str(rows[0][1]))}</p>")
        elif ar == 1 and d is not None:
            mp = dict(rows)
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th>x</th>")
            for i in range(d):
                chunks.append(f"<th>{i}</th>")
            chunks.append("</tr><tr><th>f(x)</th>")
            for i in range(d):
                chunks.append(f"<td>{esc(str(mp.get((i,), '-')))}</td>")
            chunks.append("</tr></table>")
        elif ar == 2 and d is not None:
            grid = {(a[0], a[1]): v for a, v in rows if len(a) == 2}
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th></th>")
            for j in range(d):
                chunks.append(f"<th>{j}</th>")
            chunks.append("</tr>")
            for i in range(d):
                chunks.append(f"<tr><th>{i}</th>")
                for j in range(d):
                    v = grid.get((i, j), "-")
                    chunks.append(f"<td>{esc(str(v))}</td>")
                chunks.append("</tr>")
            chunks.append("</table>")
        else:
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th>args</th><th>value</th></tr>")
            for args, v in rows[:64]:
                chunks.append(f"<tr><td>{esc(repr(args))}</td><td>{esc(str(v))}</td></tr>")
            if len(rows) > 64:
                chunks.append(f"<tr><td colspan='2'>… {len(rows) - 64} more</td></tr>")
            chunks.append("</table>")

    by_rel: dict[str, list[tuple[tuple[int, ...], bool]]] = {}
    for n, args, v in mi.relation_entries:
        by_rel.setdefault(n, []).append((args, v))
    for name in sorted(by_rel.keys()):
        rows = sorted(by_rel[name], key=lambda x: x[0])
        ar = mi._relations_map()[name]
        chunks.append(f"<h4>{esc(name)} <small>(relation, arity {ar})</small></h4>")
        if ar == 0:
            chunks.append(f"<p>{esc(str(rows[0][1]))}</p>")
        elif ar == 1 and d is not None:
            mp = {a[0]: v for a, v in rows if len(a) == 1}
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th>x</th>")
            for i in range(d):
                chunks.append(f"<th>{i}</th>")
            chunks.append("</tr><tr><th>R(x)</th>")
            for i in range(d):
                if i in mp:
                    chunks.append(f"<td>{'T' if mp[i] else 'F'}</td>")
                else:
                    chunks.append("<td>-</td>")
            chunks.append("</tr></table>")
        elif ar == 2 and d is not None:
            grid = {(a[0], a[1]): v for a, v in rows if len(a) == 2}
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th></th>")
            for j in range(d):
                chunks.append(f"<th>{j}</th>")
            chunks.append("</tr>")
            for i in range(d):
                chunks.append(f"<tr><th>{i}</th>")
                for j in range(d):
                    if (i, j) in grid:
                        chunks.append(f"<td>{'T' if grid[(i, j)] else 'F'}</td>")
                    else:
                        chunks.append("<td>-</td>")
                chunks.append("</tr>")
            chunks.append("</table>")
        else:
            chunks.append("<table class='pyp9m4-mace4interp-tbl' border='1' style='border-collapse:collapse'>")
            chunks.append("<tr><th>args</th><th>holds</th></tr>")
            for args, v in rows[:64]:
                chunks.append(f"<tr><td>{esc(repr(args))}</td><td>{esc(str(v))}</td></tr>")
            if len(rows) > 64:
                chunks.append(f"<tr><td colspan='2'>… {len(rows) - 64} more</td></tr>")
            chunks.append("</table>")

    chunks.append("</div>")
    return "".join(chunks)


@dataclass(frozen=True, slots=True)
class Mace4Parsed:
    """Result of :func:`parse_mace4_output`."""

    sections: dict[str, str]
    interpretations: tuple[Mace4Interpretation, ...]
    portable_lists: tuple[object, ...]
    """Top-level list objects from portable format (via :func:`ast.literal_eval`), if any."""

    warnings: tuple[ParseWarning, ...]


def _parse_standard_block(block: str) -> tuple[Mace4Interpretation, tuple[ParseWarning, ...]]:
    warnings: list[ParseWarning] = []
    dm = _DOMAIN_RE.search(block)
    domain = int(dm.group(1)) if dm else None
    assigns: list[StandardAssignment] = []
    for line in block.splitlines():
        line_st = line.strip()
        if not line_st or line_st.startswith("%"):
            continue
        m = _ASSIGN_LINE_RE.match(line_st)
        if m:
            assigns.append(StandardAssignment(kind=m.group(1).lower(), rhs=m.group(2).rstrip(",").strip()))
    if domain is None:
        warnings.append(ParseWarning("domain_size_not_found", "could not read interpretation(n,"))
    assign_t = tuple(assigns)
    fn_e, rel_e, fn_a, rel_a, tab_warns = _build_interpretation_tables(assign_t)
    warnings.extend(tab_warns)

    # Mace4 newer output style uses `function(sym, [values])` and
    # `relation(P(_,...), [values])` inside the interpretation body.
    fn_l, rel_l, list_style_warns = _build_tables_from_list_style(block, domain_size=domain)
    warnings.extend(list_style_warns)

    # Merge both sources into a single set of entries/arities.
    fn_map: dict[tuple[str, tuple[int, ...]], int] = {(n, a): v for n, a, v in fn_e}
    rel_map: dict[tuple[str, tuple[int, ...]], bool] = {(n, a): v for n, a, v in rel_e}
    fn_arity: dict[str, int] = {n: a for n, a in fn_a}
    rel_arity: dict[str, int] = {n: a for n, a in rel_a}

    for n, args, v in fn_l:
        ar = len(args)
        prev = fn_arity.get(n)
        if prev is not None and prev != ar:
            warnings.append(
                ParseWarning(
                    "function_arity_mismatch",
                    f"function {n!r}: arity {prev} vs {ar} (from list-style output)",
                )
            )
        fn_arity[n] = ar
        fn_map[(n, args)] = v

    for n, args, v in rel_l:
        ar = len(args)
        prev = rel_arity.get(n)
        if prev is not None and prev != ar:
            warnings.append(
                ParseWarning(
                    "relation_arity_mismatch",
                    f"relation {n!r}: arity {prev} vs {ar} (from list-style output)",
                )
            )
        rel_arity[n] = ar
        rel_map[(n, args)] = v

    fn_ar_t = tuple(sorted(fn_arity.items()))
    rel_ar_t = tuple(sorted(rel_arity.items()))
    fn_e = tuple(sorted(((n, a, v) for (n, a), v in fn_map.items()), key=lambda x: (x[0], x[1])))
    rel_e = tuple(sorted(((n, a, v) for (n, a), v in rel_map.items()), key=lambda x: (x[0], x[1])))
    return (
        Mace4Interpretation(
            raw=block,
            domain_size=domain,
            standard_assignments=assign_t,
            function_entries=fn_e,
            relation_entries=rel_e,
            function_arities=fn_ar_t,
            relation_arities=rel_ar_t,
        ),
        tuple(warnings),
    )


class Mace4InterpretationBuffer:
    """Buffer Mace4 stdout chunks and collect each complete ``interpretation(...)`` block.

    Call :meth:`feed` with successive fragments (e.g. from ``asyncio`` stream reads). Whenever
    a block's closing parenthesis arrives, the block is parsed with the same rules as
    :func:`parse_mace4_output`, so :class:`Mace4Interpretation` rows match batch parsing.

    **Portable format:** portable output is a single top-level ``[...]`` literal meant to be
    parsed with :func:`ast.literal_eval` on the **full** document. Incremental feeds cannot
    reliably detect or parse that form until EOF. For portable models, accumulate the full
    stdout string (or use :func:`parse_mace4_output` once at process exit). This buffer only
    extracts standard ``interpretation(...)`` structures incrementally.

    **Early break / cancel:** if you stop reading before the process ends, :attr:`buffered_tail`
    may hold an incomplete ``interpretation(``… fragment; discard the buffer or ignore it.
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[tuple[Mace4Interpretation, tuple[ParseWarning, ...]]]:
        """Append ``chunk`` and return newly completed interpretations (oldest first)."""
        if not chunk:
            return []
        self._buf += chunk
        out: list[tuple[Mace4Interpretation, tuple[ParseWarning, ...]]] = []
        pos = 0
        while True:
            got = _try_extract_next_interpretation(self._buf, pos)
            if got is None:
                break
            block, end = got
            mi, w = _parse_standard_block(block)
            out.append((mi, w))
            pos = end
        if pos > 0:
            self._buf = self._buf[pos:]
        return out

    def reset(self) -> None:
        """Clear the internal buffer."""
        self._buf = ""

    @property
    def buffered_tail(self) -> str:
        """Text not yet part of a complete ``interpretation(...)`` (preamble or incomplete tail)."""
        return self._buf


def _try_parse_portable(text: str) -> tuple[tuple[object, ...], tuple[ParseWarning, ...]]:
    """If ``text`` looks like a portable-format Python list, parse with :func:`ast.literal_eval`."""
    warnings: list[ParseWarning] = []
    stripped = text.strip()
    if not stripped.startswith("["):
        return (), ()
    try:
        obj = ast.literal_eval(stripped)
    except (SyntaxError, ValueError) as e:
        warnings.append(ParseWarning("portable_literal_eval_failed", str(e)))
        return (), tuple(warnings)
    if isinstance(obj, list):
        return (tuple(obj), tuple(warnings))
    return ((obj,), tuple(warnings))


def parse_mace4_output(text: str) -> Mace4Parsed:
    """Parse Mace4 text: LADR section blocks, ``interpretation`` structures, optional portable list.

    For **streaming** standard-structure output, use :class:`Mace4InterpretationBuffer` so each
    complete ``interpretation(...)`` is parsed as it arrives; that path reuses the same block
    parser as this function.

    **Portable format** (whole file a nested list) is detected when trimmed text starts with
    ``[``. It is evaluated only on the **entire** string passed here — not incrementally — so
    callers using portable mode should buffer full stdout (or pipe to a string) before
    calling. Standard ``interpretation(...)`` blocks in the same run are still extracted when
    present.

    Standard assignments are best-effort regex lines ``function = …`` / ``relation = …``.
    """
    sections, sec_warn = split_ladr_section_blocks(text)
    blocks = extract_interpretation_blocks(text)
    interp: list[Mace4Interpretation] = []
    all_warn: list[ParseWarning] = list(sec_warn)

    if not blocks and "interpretation(" in text.lower():
        all_warn.append(
            ParseWarning(
                "interpretation_unbalanced",
                "saw 'interpretation(' but could not match balanced parentheses",
            )
        )

    for b in blocks:
        mi, w = _parse_standard_block(b)
        interp.append(mi)
        all_warn.extend(w)

    portable: tuple[object, ...] = ()
    p_warn: tuple[ParseWarning, ...] = ()
    if not blocks:
        portable, p_warn = _try_parse_portable(text)
        all_warn.extend(p_warn)

    return Mace4Parsed(
        sections=sections,
        interpretations=tuple(interp),
        portable_lists=portable,
        warnings=tuple(all_warn),
    )
