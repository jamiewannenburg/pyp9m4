# pyp9m4

Python wrapper for **Prover9**, **Mace4**, and related [LADR](https://www.cs.unm.edu/~mccune/mace4/) command-line tools. It resolves pinned binaries (or your own install), runs them via **asyncio** with sync helpers for scripts and notebooks, and returns **parsed** proof and model output. Typed CLI option dataclasses live under `pyp9m4.options`.

- **Python**: 3.10+
- **License**: GPL-2.0 (wrapper; downloaded binaries are separate artifacts)

## Installation

The package is **not published on PyPI yet**. Install from your Git repository (replace the URL with yours once it exists):

```bash
pip install "pyp9m4 @ git+https://github.com/<user-or-org>/pyp9m4.git"
```

Pin a branch or tag if you need to:

```bash
pip install "pyp9m4 @ git+https://github.com/<user-or-org>/pyp9m4.git@main"
```

Optional extras (see `pyproject.toml`):

```bash
pip install "pyp9m4[smt] @ git+https://github.com/<user-or-org>/pyp9m4.git"
```

For development and tests, clone and use an editable install:

```bash
git clone https://github.com/<user-or-org>/pyp9m4.git
cd pyp9m4
pip install -e ".[dev]"
```

When a PyPI release exists, `pip install pyp9m4` will work as usual.

## Resolving binaries

Facades use `BinaryResolver` by default. It downloads a **pinned** release from [jamiewannenburg/ladr](https://github.com/jamiewannenburg/ladr) into the user cache (via `platformdirs`). You can override with:

| Variable | Effect |
|----------|--------|
| `LADR_BIN_DIR` | Directory containing `prover9`, `mace4`, etc. (highest priority) |
| `PROVER9_HOME` / `MACE4_HOME` | Install roots for those two tools |
| `GITHUB_TOKEN` or `GH_TOKEN` | Optional, for GitHub API rate limits when downloading |

The pinned tag is exposed as `pyp9m4.BINARIES_VERSION`.

## Quick start (sync)

Set **defaults once** on the facade; override per call with `options=` or keyword arguments that map to `Prover9CliOptions` / `Mace4CliOptions` fields (plus `timeout_s`, and for Mace4 `eliminate_isomorphic`).

```python
from pathlib import Path

from pyp9m4 import Mace4, Prover9
from pyp9m4.options import Mace4CliOptions, Prover9CliOptions

# Defaults: e.g. global timeout
p9 = Prover9(timeout_s=120)
proof = p9.run(Path("problem.in"))  # or stdin string/bytes
print(proof.parsed.statistics)
print(proof.stdout[:200])  # raw output still available

# Per-call override: replace baseline options or patch fields via kwargs
proof2 = p9.run(
    Path("other.in"),
    options=Prover9CliOptions(),  # replaces instance baseline for this call
    timeout_s=60,
)

m4 = Mace4(timeout_s=120, domain_size=2)  # kwargs apply to default Mace4CliOptions
for model in m4.models(problem_text_or_path):  # first arg is ``input`` (str, bytes, or Path)
    print(model.domain_size)
```

`Prover9.run` and `Mace4.models` use a helper that is safe from **Jupyter/IPython** when an event loop is already running.

### Lifecycle vs semantic outcome vs aliases

| | |
|--|--|
| `proof.lifecycle` | How the wrapper subprocess finished: `succeeded`, `failed`, `timed_out`, `cancelled`, etc. |
| `proof.outcome` | Logical verdict from the Prover9 log (`ProverOutcome`): e.g. `proved`, `not_proved`, `unknown`, or `error` / `timed_out` / `cancelled` when the run did not succeed cleanly. |

Use `from pyp9m4 import ProverOutcome, infer_prover_outcome` if you parse stdout yourself. For a succeeded run without a clear `THEOREM PROVED` line, `outcome` may be `unknown` until more exit phrases are classified.

**Naming aliases (same behavior as the canonical methods):**

- Prover9: `prove` / `aprove` / `start_aprove` delegate to `run` / `arun` / `start_arun`.
- Mace4: `counterexamples` / `acounterexamples` / `start_acounterexamples` delegate to `models` / `amodels` / `start_amodels`.
- `Mace4Interpretation`: `get_value` and `model_eval` delegate to `value_at` (SMT-style naming).

## Async: `arun`, `amodels`, and background jobs

```python
import asyncio
from pyp9m4 import Prover9

async def main():
    p9 = Prover9(timeout_s=120)
    proof = await p9.arun("formulas go here ...")
    print(proof.lifecycle, proof.parsed.statistics)

asyncio.run(main())
```

For **non-blocking** runs (e.g. a web API that stores a job id and polls), use `start_arun` / `start_amodels`. Call `await handle.status()` on the **same asyncio event loop** that started the job. Serialize snapshots with `job_status_snapshot_to_json_dict`.

```python
import asyncio
from pyp9m4 import Mace4, Prover9, job_status_snapshot_to_json_dict

async def poll_example():
    p9 = Prover9(timeout_s=120)
    job = p9.start_arun(problem_path_or_string)
    while True:
        snap = await job.status()
        payload = job_status_snapshot_to_json_dict(snap)
        # return payload from a GET /jobs/{id} handler
        if snap.lifecycle in ("succeeded", "failed", "timed_out", "cancelled"):
            break
        await asyncio.sleep(0.1)
    result = await job.result()
    return result

async def mace4_background():
    m4 = Mace4(timeout_s=120, domain_size=2)
    job = m4.start_amodels(problem_text)
    async for model in job.amodels():
        ...  # consume while another task polls await job.status()
    await job.wait()
```

Mace4 `status()` includes best-effort fields such as `models_found` and `last_domain_size`; treat them as hints, not full solver internals.

## Typed CLI options

Each tool has a dataclass with `to_argv()` returning fragments **after** the executable name (`pyp9m4.options`):

- `Prover9CliOptions`, `Mace4CliOptions`, `InterpformatCliOptions`, `IsofilterCliOptions`, `ProofTransCliOptions`

Facades merge these with constructor and call-time kwargs. With `eliminate_isomorphic=True`, Mace4 runs `mace4 | interpformat | isofilter` (models appear after the pipeline completes, not streamed across tools).

## Parsers

- `parse_prover9_output(stdout)` — statistics, proof segments, warnings
- `parse_mace4_output(stdout)` — interpretations / models
- `parse_pipeline_tool_output`, `inspect_pipeline_text` — lighter pipeline helpers

Facades already parse for you; use these when you have raw stdout from elsewhere.

## Advanced: subprocess runner and custom `argv`

For tools without a facade (e.g. `prooftrans`) or fully custom invocations, build `argv` from `options.to_argv()` and use `SubprocessInvocation` with `run_sync` or `AsyncToolRunner`:

```python
from pathlib import Path

from pyp9m4 import BinaryResolver, SubprocessInvocation, RunStatus, run_sync
from pyp9m4.options import Prover9CliOptions

resolver = BinaryResolver()
prover9 = resolver.resolve("prover9")
opts = Prover9CliOptions(input_files=(str(Path("problem.in")),))
inv = SubprocessInvocation(argv=(str(prover9), *opts.to_argv()), timeout_s=120)
result = run_sync(inv)
assert result.status == RunStatus.SUCCEEDED
```

Streaming line-level events: `AsyncToolRunner().stream_events(inv)` and `stream_events_sync(inv)` for small outputs.

## Example notebook

Source of truth is the **Jupytext** percent script `examples/pyp9m4_example.py` (cells use `# %%`; `%pwd` and `%time` need an **IPython** kernel). Regenerate the `.ipynb`:

```bash
pip install jupytext
jupytext --to ipynb examples/pyp9m4_example.py -o examples/pyp9m4_example.ipynb
```

Use a kernel whose Python has `pyp9m4` installed (e.g. `pip install -e .` from the repo root). For headless execution, register the venv once and select it:

```bash
python -m ipykernel install --user --name=pyp9m4-venv --display-name="Python (pyp9m4 venv)"
jupyter nbconvert --to notebook --execute examples/pyp9m4_example.ipynb --ExecutePreprocessor.kernel_name=pyp9m4-venv
```

(Requires network on first run if LADR binaries are not cached yet.)

## Tests

```bash
pytest
pytest -m integration   # downloads or uses LADR_BIN_DIR; slower
```
