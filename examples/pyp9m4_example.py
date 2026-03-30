# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
# ---

# %% [markdown]
# # pyp9m4 example
#
# This file uses the **percent** (Spyder / Jupytext) format: cells start with `# %%`.
# **Line magics** (`%pwd`, ``%time <expr>``) require an **IPython** kernel. Use
# ``time.perf_counter()`` to time runs; use ``%time`` only on expressions
# (e.g. ``%time len(s)``), not on assignments.
#
# The examples use the high-level :class:`~pyp9m4.Prover9` and :class:`~pyp9m4.Mace4` facades
# (constructor defaults, per-call overrides). The last section shows a **low-level** ``prooftrans``
# invocation. Regenerate the notebook: ``jupytext --to ipynb pyp9m4_example.py -o pyp9m4_example.ipynb``

# %%
from pathlib import Path
from time import perf_counter

from pyp9m4 import (
    BINARIES_VERSION,
    BinaryResolver,
    Mace4,
    Prover9,
    RunStatus,
    SubprocessInvocation,
    detect_platform_key,
    job_status_snapshot_to_json_dict,
    run_sync,
)
from pyp9m4.options import Mace4CliOptions, Prover9CliOptions


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:
        cwd = Path.cwd()
        if (cwd / "pyp9m4").is_dir() and (cwd / "pyproject.toml").is_file():
            return cwd
        if cwd.name == "examples" and (cwd.parent / "pyp9m4").is_dir():
            return cwd.parent
        return cwd


_REPO_ROOT = _repo_root()
_E2E = _REPO_ROOT / "tests" / "corpus" / "e2e"

print("BINARIES_VERSION:", BINARIES_VERSION)
print("platform key:", detect_platform_key())
%pwd

# %% [markdown]
# ## Prover9 facade
#
# Set shared defaults on the instance (e.g. ``timeout_s``). Override per call with ``options=``
# or keyword arguments that match :class:`~pyp9m4.options.prover9.Prover9CliOptions` fields.

# %%
p9 = Prover9(timeout_s=120)
trivial = _E2E / "trivial.in"

_t0 = perf_counter()
proof = p9.run(trivial)
print(f"prover9 run: {perf_counter() - _t0:.3f}s")
proof.lifecycle, proof.outcome, proof.exit_code, proof.parsed.statistics, len(proof.parsed.proof_segments)
%time len(proof.stdout)

# %%
# Per-call override: replace baseline options for this call, then patch with kwargs.
proof2 = p9.run(
    trivial,
    options=Prover9CliOptions(),
    timeout_s=60,
)

# %% [markdown]
# ## Mace4 facade: streaming models
#
# :meth:`~pyp9m4.Mace4.models` yields interpretations as Mace4 prints them (unless
# ``eliminate_isomorphic=True``, which runs the full pipeline before yielding).

# %%
mace_body = (_E2E / "mace4_sat.in").read_text(encoding="utf-8")
m4 = Mace4(timeout_s=120, domain_size=2)

_t0 = perf_counter()
models = list(m4.models(mace_body))
print(f"mace4 models(): {perf_counter() - _t0:.3f}s, count={len(models)}")
models[0].domain_size

# %% [markdown]
# ## Async background jobs and ``status()`` (polling)
#
# ``start_arun`` / ``start_amodels`` return immediately. Use ``await handle.status()`` on the
# **same asyncio event loop** that started the job; ``job_status_snapshot_to_json_dict`` gives
# JSON-friendly dicts for APIs.
#
# In Jupyter you can use top-level ``await`` instead of ``asyncio.run(...)`` if your kernel supports it.

# %%
import asyncio


async def demo_background_poll() -> None:
    p9 = Prover9(timeout_s=120)
    job = p9.start_arun(trivial)
    while True:
        snap = await job.status()
        print("prover9 job:", job_status_snapshot_to_json_dict(snap))
        if snap.lifecycle in ("succeeded", "failed", "timed_out", "cancelled"):
            break
        await asyncio.sleep(0.02)
    final = await job.result()
    print("done:", final.lifecycle, final.parsed.statistics)

    m4a = Mace4(timeout_s=120, domain_size=2)
    jm = m4a.start_amodels(mace_body)
    poll_n = 0
    while poll_n < 50:
        sm = await jm.status()
        if sm.lifecycle != "running" and sm.lifecycle != "pending":
            break
        poll_n += 1
        await asyncio.sleep(0.02)
    async for m in jm.amodels():
        print("model domain_size:", m.domain_size)
    await jm.wait()
    print("mace4 final:", job_status_snapshot_to_json_dict(await jm.status()))


asyncio.run(demo_background_poll())

# %% [markdown]
# ## Advanced: custom ``argv`` (e.g. prooftrans)
#
# For tools without a high-level facade, resolve binaries and use
# :class:`~pyp9m4.SubprocessInvocation` with :func:`~pyp9m4.run_sync`.

# %%
resolver = BinaryResolver()
prooftrans = resolver.resolve("prooftrans")
# Re-run trivial proof to feed prooftrans stdin
proof_for_pipe = Prover9(timeout_s=120).run(trivial)
inv_pt = SubprocessInvocation(argv=(str(prooftrans),), stdin=proof_for_pipe.stdout, timeout_s=120)

_t0 = perf_counter()
res_pt = run_sync(inv_pt)
print(f"prooftrans run: {perf_counter() - _t0:.3f}s")
res_pt.status == RunStatus.SUCCEEDED, ("PROOF" in res_pt.stdout or "proof" in res_pt.stdout.lower())
