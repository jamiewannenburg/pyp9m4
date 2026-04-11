"""Typed fluent pipe stages: chain subprocesses on one async runner with blocking ``output()`` / ``stream()``."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Queue
from typing import Final

from pyp9m4.io_kinds import IOKind
from pyp9m4.parsers import Interpretation
from pyp9m4.parsers.mace4 import Mace4InterpretationBuffer
from pyp9m4.parsers.prover9 import ProofSegment, parse_prover9_output
from pyp9m4.runner import (
    AsyncToolRunner,
    RunStatus,
    SubprocessInvocation,
    _sync_run_awaitable,
)

_TOOL_IO: Final[dict[str, tuple[IOKind, IOKind]]] = {
    "prover9": (IOKind.THEORY, IOKind.PROOFS),
    "fof_prover9": (IOKind.THEORY, IOKind.PROOFS),
    "mace4": (IOKind.THEORY, IOKind.INTERPRETATIONS),
    "interpformat": (IOKind.INTERPRETATIONS, IOKind.INTERPRETATIONS),
    "isofilter": (IOKind.INTERPRETATIONS, IOKind.INTERPRETATIONS),
    "isofilter2": (IOKind.INTERPRETATIONS, IOKind.INTERPRETATIONS),
    "prooftrans": (IOKind.PROOFS, IOKind.PROOFS),
    "interpfilter": (IOKind.INTERPRETATIONS, IOKind.INTERPRETATIONS),
    "clausefilter": (IOKind.FORMULAS, IOKind.FORMULAS),
    "clausetester": (IOKind.FORMULAS, IOKind.CLAUSETESTER_REPORT),
    "tptp_to_ladr": (IOKind.TPTP_TEXT, IOKind.LADR_BARE_INPUT),
    "ladr_to_tptp": (IOKind.THEORY, IOKind.TPTP_TEXT),
    "rewriter": (IOKind.TERMS, IOKind.TERMS),
    "renamer": (IOKind.LADR_TEXT, IOKind.LADR_TEXT),
    "test_clause_eval": (IOKind.LADR_TEXT, IOKind.LADR_TEXT),
}

_TOOL_NAME_ALIASES: Final[dict[str, str]] = {
    "if": "isofilter",
    "iso": "isofilter",
    "interp": "interpformat",
    "ifc": "interpformat",
    "modelformat": "interpformat",
    "pt": "prooftrans",
}


def tool_stdio_kinds(tool: str) -> tuple[IOKind, IOKind]:
    """Return ``(stdin_kind, stdout_kind)`` for a resolvable LADR tool name (for docs / validation)."""
    n = tool.strip().lower().replace("-", "_")
    n = _TOOL_NAME_ALIASES.get(n, n)
    try:
        return _TOOL_IO[n]
    except KeyError as e:
        raise ValueError(f"unknown tool for I/O kinds: {tool!r}") from e


@dataclass(frozen=True, slots=True)
class PipeRunResult:
    """Outcome of :meth:`Stage.output` / :meth:`Stage.aoutput`."""

    stdout: str
    stderr: str
    status: RunStatus
    exit_code: int | None
    stderr_per_stage: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == RunStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class Stage:
    """Linear chain of :class:`SubprocessInvocation` with semantic I/O kinds for safe piping.

    Use :meth:`source` to start from stdin text/bytes, then :meth:`with_step` for each process.
    Run with :meth:`output` (buffered stdout) or :meth:`stream` / :meth:`astream` (incremental).
    """

    initial_stdin: str | bytes | None
    in_kind: IOKind
    out_kind: IOKind
    invocations: tuple[SubprocessInvocation, ...]
    cwd: Path | str | None = None
    env: dict[str, str] | None = None
    timeout_s: float | None = None

    @classmethod
    def source(
        cls,
        stdin: str | bytes | None,
        *,
        kind: IOKind,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> Stage:
        """First segment: data of semantic kind ``kind`` becomes stdin of the first subprocess."""
        return cls(
            initial_stdin=stdin,
            in_kind=kind,
            out_kind=kind,
            invocations=(),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            timeout_s=timeout_s,
        )

    def _merge_invocation(self, inv: SubprocessInvocation) -> SubprocessInvocation:
        cwd = inv.cwd if inv.cwd is not None else self.cwd
        timeout_s = inv.timeout_s if inv.timeout_s is not None else self.timeout_s
        base = dict(self.env) if self.env else {}
        over = dict(inv.env) if inv.env else {}
        merged_env = {**base, **over}
        env_final: dict[str, str] | None = merged_env if merged_env else None
        return replace(inv, cwd=cwd, timeout_s=timeout_s, env=env_final)

    def with_step(
        self,
        inv: SubprocessInvocation,
        *,
        produces: IOKind,
        expects: IOKind | None = None,
        output_file: Path | str | None = None,
    ) -> Stage:
        """Append a subprocess; optional ``output_file`` tees its stdout (see :attr:`SubprocessInvocation.tee_stdout_path`)."""
        exp = self.out_kind if expects is None else expects
        if self.out_kind != exp:
            raise TypeError(
                f"pipe stage type mismatch: current data kind is {self.out_kind.value!r}, "
                f"but this step declares stdin kind {exp.value!r}"
            )
        merged = self._merge_invocation(inv)
        if output_file is not None:
            merged = replace(merged, tee_stdout_path=output_file)
        new_invs = self.invocations + (merged,)
        return replace(
            self,
            out_kind=produces,
            invocations=new_invs,
        )

    def _require_steps(self) -> None:
        if not self.invocations:
            raise ValueError("Stage has no steps; add at least one with .with_step()")

    def _require_interpretations_stage(self, method: str) -> None:
        if self.out_kind != IOKind.INTERPRETATIONS:
            raise TypeError(
                f"{method}() requires a pipe whose final output is interpretations "
                f"(Mace4 / isofilter / … stream); got {self.out_kind.value!r}"
            )

    def _require_proofs_stage(self, method: str) -> None:
        if self.out_kind != IOKind.PROOFS:
            raise TypeError(
                f"{method}() requires a pipe whose final output is proofs "
                f"(Prover9 / prooftrans log); got {self.out_kind.value!r}"
            )

    def _effective_timeout(self) -> float | None:
        if self.timeout_s is not None:
            return self.timeout_s
        timeouts = [inv.timeout_s for inv in self.invocations if inv.timeout_s is not None]
        return max(timeouts) if timeouts else None

    async def aoutput(self) -> PipeRunResult:
        self._require_steps()
        runner = AsyncToolRunner()
        st, code, out, err, per = await runner.run_pipe_chain(
            list(self.invocations),
            initial_stdin=self.initial_stdin,
            timeout_s=self._effective_timeout(),
        )
        return PipeRunResult(
            stdout=out,
            stderr=err,
            status=st,
            exit_code=code,
            stderr_per_stage=per,
        )

    def output(self) -> PipeRunResult:
        """Run the full chain to completion; return captured stdout and metadata."""
        return _sync_run_awaitable(self.aoutput)

    async def astream(self, *, lines: bool = True) -> AsyncIterator[str]:
        """Async iterator over final-process stdout (lines or raw decoded chunks)."""
        self._require_steps()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        exc_holder: list[BaseException] = []

        async def on_line(line: str) -> None:
            await queue.put(line)

        async def on_chunk(chunk: bytes) -> None:
            if not chunk:
                return
            enc = self.invocations[0].encoding
            err = self.invocations[0].errors
            await queue.put(chunk.decode(enc, errors=err))

        async def producer() -> None:
            try:
                runner = AsyncToolRunner()
                if lines:
                    await runner.run_pipe_chain(
                        list(self.invocations),
                        initial_stdin=self.initial_stdin,
                        timeout_s=self._effective_timeout(),
                        accumulate_last_stdout=False,
                        on_last_stdout_line=on_line,
                    )
                else:
                    await runner.run_pipe_chain(
                        list(self.invocations),
                        initial_stdin=self.initial_stdin,
                        timeout_s=self._effective_timeout(),
                        accumulate_last_stdout=False,
                        on_last_stdout_chunk=on_chunk,
                    )
            except BaseException as e:
                exc_holder.append(e)
            finally:
                with contextlib.suppress(Exception):
                    await queue.put(None)

        task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            with contextlib.suppress(Exception):
                await task
            if exc_holder:
                raise exc_holder[0]

    def stream(self, *, lines: bool = True) -> Iterator[str]:
        """Blocking iterator over final stdout as lines (default) or decoded chunks."""
        self._require_steps()
        sync_q: Queue[str | None] = Queue()
        exc_holder: list[BaseException] = []

        async def on_line(line: str) -> None:
            sync_q.put(line)

        async def on_chunk(chunk: bytes) -> None:
            if not chunk:
                return
            enc = self.invocations[0].encoding
            err = self.invocations[0].errors
            sync_q.put(chunk.decode(enc, errors=err))

        async def work() -> None:
            try:
                runner = AsyncToolRunner()
                if lines:
                    await runner.run_pipe_chain(
                        list(self.invocations),
                        initial_stdin=self.initial_stdin,
                        timeout_s=self._effective_timeout(),
                        accumulate_last_stdout=False,
                        on_last_stdout_line=on_line,
                    )
                else:
                    await runner.run_pipe_chain(
                        list(self.invocations),
                        initial_stdin=self.initial_stdin,
                        timeout_s=self._effective_timeout(),
                        accumulate_last_stdout=False,
                        on_last_stdout_chunk=on_chunk,
                    )
            except BaseException as e:
                exc_holder.append(e)
            finally:
                sync_q.put(None)

        def thread_main() -> None:
            try:
                _sync_run_awaitable(work)
            except BaseException as e:
                if not exc_holder:
                    exc_holder.append(e)
                sync_q.put(None)

        thread = threading.Thread(target=thread_main, daemon=True)
        thread.start()
        try:
            while True:
                item = sync_q.get()
                if item is None:
                    break
                yield item
        finally:
            thread.join(timeout=600.0)
        if exc_holder:
            raise exc_holder[0]

    async def ainterps(self) -> AsyncIterator[Interpretation]:
        """Async iterator over completed ``interpretation(...)`` values from the final stdout stream.

        Feeds each decoded stdout line (plus newline) into :class:`~pyp9m4.parsers.mace4.Mace4InterpretationBuffer`
        while the pipe runs—same incremental rules as the buffer (portable ``[...]`` models need full-document
        parsing instead).
        """
        self._require_steps()
        self._require_interpretations_stage("ainterps")
        buf = Mace4InterpretationBuffer()
        queue: asyncio.Queue[Interpretation | None] = asyncio.Queue()
        exc_holder: list[BaseException] = []

        async def on_line(line: str) -> None:
            for mi, _w in buf.feed(line + "\n"):
                await queue.put(mi)

        async def producer() -> None:
            try:
                runner = AsyncToolRunner()
                await runner.run_pipe_chain(
                    list(self.invocations),
                    initial_stdin=self.initial_stdin,
                    timeout_s=self._effective_timeout(),
                    accumulate_last_stdout=False,
                    on_last_stdout_line=on_line,
                )
            except BaseException as e:
                exc_holder.append(e)
            finally:
                with contextlib.suppress(Exception):
                    await queue.put(None)

        task = asyncio.create_task(producer())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            with contextlib.suppress(Exception):
                await task
            if exc_holder:
                raise exc_holder[0]

    def interps(self) -> Iterator[Interpretation]:
        """Blocking counterpart of :meth:`ainterps`."""
        self._require_steps()
        self._require_interpretations_stage("interps")
        sync_q: Queue[Interpretation | None] = Queue()
        exc_holder: list[BaseException] = []
        buf = Mace4InterpretationBuffer()

        async def on_line(line: str) -> None:
            for mi, _w in buf.feed(line + "\n"):
                sync_q.put(mi)

        async def work() -> None:
            try:
                runner = AsyncToolRunner()
                await runner.run_pipe_chain(
                    list(self.invocations),
                    initial_stdin=self.initial_stdin,
                    timeout_s=self._effective_timeout(),
                    accumulate_last_stdout=False,
                    on_last_stdout_line=on_line,
                )
            except BaseException as e:
                exc_holder.append(e)
            finally:
                sync_q.put(None)

        def thread_main() -> None:
            try:
                _sync_run_awaitable(work)
            except BaseException as e:
                if not exc_holder:
                    exc_holder.append(e)
                sync_q.put(None)

        thread = threading.Thread(target=thread_main, daemon=True)
        thread.start()
        try:
            while True:
                item = sync_q.get()
                if item is None:
                    break
                yield item
        finally:
            thread.join(timeout=600.0)
        if exc_holder:
            raise exc_holder[0]

    def interpretations(self) -> Iterator[Interpretation]:
        """Alias of :meth:`interps`."""
        yield from self.interps()

    def models(self) -> Iterator[Interpretation]:
        """Alias of :meth:`interps` (:class:`~pyp9m4.parsers.Interpretation` is also named ``Model``)."""
        yield from self.interps()

    async def _proof_segments_from_run(self, *, for_method: str) -> tuple[ProofSegment, ...]:
        self._require_steps()
        self._require_proofs_stage(for_method)
        runner = AsyncToolRunner()
        _st, _code, out, _err, _per = await runner.run_pipe_chain(
            list(self.invocations),
            initial_stdin=self.initial_stdin,
            timeout_s=self._effective_timeout(),
        )
        return parse_prover9_output(out).proof_segments

    async def aproofs(self) -> AsyncIterator[ProofSegment]:
        """Yield coarse proof units from :func:`~pyp9m4.parsers.prover9.parse_prover9_output` after the run finishes.

        This is a **stub**: stdout is accumulated internally, then ``proof_segments`` are emitted. The format may
        evolve when a structured proof AST exists.
        """
        for seg in await self._proof_segments_from_run(for_method="aproofs"):
            yield seg

    def proofs(self) -> Iterator[ProofSegment]:
        """Blocking counterpart of :meth:`aproofs`."""

        async def collect() -> tuple[ProofSegment, ...]:
            return await self._proof_segments_from_run(for_method="proofs")

        return iter(_sync_run_awaitable(collect))


Pipe = Stage
