"""Logical verdict for a Prover9 run (separate from subprocess :class:`~pyp9m4.jobs.JobLifecycle`)."""

from __future__ import annotations

import enum

from pyp9m4.jobs import JobLifecycle
from pyp9m4.parsers.prover9 import Prover9Parsed

_THEOREM_PROVED = "THEOREM PROVED"


class ProverOutcome(str, enum.Enum):
    """What the Prover9 log indicates about the theorem, when distinguishable.

    This is not the same as :data:`~pyp9m4.jobs.JobLifecycle`: the latter describes how the
    wrapper subprocess finished; this describes the **logical** result when the process
    succeeded and produced parseable output. For non-``succeeded`` lifecycles, :func:`infer_prover_outcome`
    maps to ``error``, ``timed_out``, or ``cancelled`` without interpreting the log.
    """

    proved = "proved"
    not_proved = "not_proved"
    unknown = "unknown"
    error = "error"
    timed_out = "timed_out"
    cancelled = "cancelled"


def infer_prover_outcome(
    parsed: Prover9Parsed,
    *,
    lifecycle: JobLifecycle,
    exit_code: int | None,
    stdout: str,
) -> ProverOutcome:
    """Derive a :class:`ProverOutcome` from parsed output and subprocess lifecycle.

    Precedence: if ``lifecycle`` is not ``"succeeded"``, return ``error`` / ``timed_out`` /
    ``cancelled`` as appropriate (or ``unknown`` for ``pending`` / ``running``, which are
    unusual on a finished result). Do not treat partial stdout as **proved** in those cases.

    When ``lifecycle == "succeeded"``:

    - **proved** if ``THEOREM PROVED`` appears in ``stdout`` or in trailing ``exit_phrases``, or
      if ``STATISTICS`` contains ``proofs`` with a positive integer.
    - **not_proved** if the log explicitly indicates failure to prove (see module patterns).
    - **unknown** otherwise (ambiguous or unclassified success output).

    Heuristics for **not_proved** are conservative: only match documented Prover9 phrases.
    """

    if lifecycle == "failed":
        return ProverOutcome.error
    if lifecycle == "timed_out":
        return ProverOutcome.timed_out
    if lifecycle == "cancelled":
        return ProverOutcome.cancelled
    if lifecycle in ("pending", "running"):
        return ProverOutcome.unknown

    # succeeded (or any other string — treat as success path only for "succeeded")
    if lifecycle != "succeeded":
        return ProverOutcome.unknown

    if _THEOREM_PROVED in stdout or any(_THEOREM_PROVED in line for line in parsed.exit_phrases):
        return ProverOutcome.proved

    proofs_s = parsed.statistics.get("proofs")
    if proofs_s is not None and proofs_s.isdigit() and int(proofs_s) > 0:
        return ProverOutcome.proved

    text = "\n".join(parsed.exit_phrases)
    combined = f"{stdout}\n{text}"
    if "THEOREM NOT PROVED" in combined:
        return ProverOutcome.not_proved

    return ProverOutcome.unknown
