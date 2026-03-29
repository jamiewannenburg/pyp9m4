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
# ``time.perf_counter()`` to time subprocess runs; use ``%time`` only on expressions
# (e.g. ``%time len(s)``), not on assignments.
#
# Regenerate the notebook: `jupytext --to ipynb pyp9m4_example.py -o pyp9m4_example.ipynb`

# %%
from pathlib import Path
from time import perf_counter

from pyp9m4 import (
    BINARIES_VERSION,
    BinaryResolver,
    RunStatus,
    SubprocessInvocation,
    SyncToolRunner,
    detect_platform_key,
    parse_mace4_output,
    parse_prover9_output,
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

# %%
resolver = BinaryResolver()
prover9 = resolver.resolve("prover9")
mace4 = resolver.resolve("mace4")
print("prover9:", prover9)
print("mace4:", mace4)

# %%
opts_p9 = Prover9CliOptions(input_files=(str(_E2E / "trivial.in"),))
inv_p9 = SubprocessInvocation(argv=(str(prover9), *opts_p9.to_argv()), timeout_s=120)
runner = SyncToolRunner()

# %%
_t0 = perf_counter()
res_p9 = runner.run(inv_p9)
print(f"prover9 run: {perf_counter() - _t0:.3f}s")
res_p9.status, res_p9.exit_code, res_p9.duration_s
%time len(res_p9.stdout)

# %%
assert res_p9.status == RunStatus.SUCCEEDED
parsed_p9 = parse_prover9_output(res_p9.stdout)
parsed_p9.statistics, len(parsed_p9.proof_segments)

# %%
mace_body = (_E2E / "mace4_sat.in").read_text(encoding="utf-8")
opts_m4 = Mace4CliOptions(domain_size=2)
inv_m4 = SubprocessInvocation(
    argv=(str(mace4), *opts_m4.to_argv()),
    stdin=mace_body,
    timeout_s=120,
)

# %%
_t0 = perf_counter()
res_m4 = runner.run(inv_m4)
print(f"mace4 run: {perf_counter() - _t0:.3f}s")
res_m4.status, res_m4.exit_code

# %%
assert res_m4.status == RunStatus.SUCCEEDED
parsed_m4 = parse_mace4_output(res_m4.stdout)
[len(parsed_m4.interpretations), parsed_m4.interpretations[0].domain_size]

# %%
prooftrans = resolver.resolve("prooftrans")
inv_pt = SubprocessInvocation(argv=(str(prooftrans),), stdin=res_p9.stdout, timeout_s=120)

# %%
_t0 = perf_counter()
res_pt = runner.run(inv_pt)
print(f"prooftrans run: {perf_counter() - _t0:.3f}s")
res_pt.exit_code, ("PROOF" in res_pt.stdout or "proof" in res_pt.stdout.lower())
