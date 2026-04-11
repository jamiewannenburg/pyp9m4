# pyp9m4

Python wrapper for **Prover9**, **Mace4**, and related [LADR](https://www.cs.unm.edu/~mccune/mace4/) command-line tools. It resolves pinned binaries (or your own install), runs them via **asyncio** with sync helpers for scripts and notebooks, and returns **parsed** proof and model output. Typed CLI option dataclasses live under `pyp9m4.options`.

- **Python**: 3.10+
- **License**: GPL-2.0 (wrapper; downloaded binaries are separate artifacts)

## Installation

The package is **not published on PyPI yet**. Install from your Git repository (replace the URL with yours once it exists):

```bash
pip install "pyp9m4 @ git+https://github.com/jamiewannenburg/pyp9m4.git"
```

Pin a branch or tag if you need to:

```bash
pip install "pyp9m4 @ git+https://github.com/jamiewannenburg/pyp9m4.git@main"
```

Optional extras (see `pyproject.toml`):

```bash
pip install "pyp9m4[smt] @ git+https://github.com/jamiewannenburg/pyp9m4.git"
```

For development and tests, clone and use an editable install:

```bash
git clone https://github.com/jamiewannenburg/pyp9m4.git
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

## Fluent theory → tool chains

Build a **typed linear pipe** from :class:`~pyp9m4.theory.Theory` (or :meth:`~pyp9m4.pipe.Stage.source`) with `.mace4()`, `.prover9()`, `.isofilter()`, `.interpfilter()`, and other methods on :class:`~pyp9m4.pipe.Stage` (alias ``Pipe``). Each step checks that the previous stage’s output **kind** matches what the tool expects (theory, interpretations, proofs, formulas, …). Run the chain with blocking **`.output()`** (returns :class:`~pyp9m4.pipe.PipeRunResult` with ``stdout`` / ``stderr``), **`.stream()`** (line or chunk iterator), **`.interps()`** / **`.models()`** when the final output is interpretations, or **`.proofs()`** for proof logs. Pass **`output_file=`** on a step to tee that subprocess’s stdout to a path while still feeding the next stage. Optional async variants use an **`a`** prefix (e.g. :meth:`~pyp9m4.pipe.Stage.aoutput`).

```python
from pyp9m4 import Theory

# Example shape (adjust formulas / tests to your problem):
run = (
    Theory(assumptions=["P."], goals=["Q."])
    .mace4(max_seconds=60)
    .isofilter()
    .interpfilter(formulas="R(x).", test="all_true")
    .output()
)
print(run.ok, run.stdout[:200])
```

See also :func:`~pyp9m4.pipe.tool_stdio_kinds` and :mod:`pyp9m4.io_kinds` for stdin/stdout roles.

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
- :class:`~pyp9m4.Interpretation` (alias ``Model``): `get_value` and `model_eval` delegate to `value_at` (SMT-style naming).

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

## API-oriented usage (dispatch, JSON, jobs)

The package root (`import pyp9m4`) exposes a **stable surface** for HTTP or other callers: unified tool dispatch, JSON-friendly snapshots, optional ingestion helpers for nested request bodies, and job orchestration.

| Area | Symbols (from `pyp9m4` unless noted) |
|------|-------------------------------------|
| Single entry point | `arun`, `normalize_tool_name`, `ToolName`, `ToolRegistry`, `ToolRunEnvelope` |
| Loose option bodies | `unwrap_gui_value`, `coerce_mapping`, `cli_options_from_nested_dict`; per-tool `from_nested_dict` on dataclasses under `pyp9m4.options` |
| JSON | `.to_dict()` on envelopes, results, and snapshots; `dataclass_to_json_dict`, `jsonify_for_api`, `job_status_snapshot_to_json_dict` |
| Jobs | `JobManager`, `ManagedJobSnapshot`, `JobMetadata`; combine with `start_arun` / `start_amodels` handles |
| Streaming (e.g. SSE) | `async for event in handle.event_stream():` — each `event` is a small `dict` (`stdout`, `stderr`, `model_found`, `lifecycle_change`, …) |

Example: unified dispatch and a JSON-serializable envelope (options can be a mapping or a CLI dataclass instance):

```python
import asyncio
from pyp9m4 import arun, cli_options_from_nested_dict
from pyp9m4.options import Prover9CliOptions

async def main():
    body = {"max_seconds": {"value": 120}}
    opts = cli_options_from_nested_dict(Prover9CliOptions, body)
    envelope = await arun("prover9", "formulas ...", options=opts)
    return envelope.to_dict()

asyncio.run(main())
```

For a full list of names re-exported from the package, see `__all__` in `pyp9m4/__init__.py`.

## Typed CLI options

Each tool has a dataclass with `to_argv()` returning fragments **after** the executable name (`pyp9m4.options`):

- `Prover9CliOptions`, `Mace4CliOptions`, `InterpformatCliOptions`, `IsofilterCliOptions`, `ProofTransCliOptions`

Facades merge these with constructor and call-time kwargs. With `eliminate_isomorphic=True`, Mace4 runs `mace4 | interpformat | isofilter` (models appear after the pipeline completes, not streamed across tools).

## Multi-step pipeline (`pipeline`)

`pipeline(...).run(...).pipe(...).execute()` chains tools by feeding each stage’s stdout to the next. **By default**, subprocesses are connected with 64 KiB byte pumps so intermediate stages do not buffer full stdout in Python. Pass `stream_intermediate=False` to restore the previous behaviour (each stage’s full stdout is collected before the next tool runs).

For large final output, set `buffer_last_stdout=False` and use one or more of:

- `last_stdout_path` — append (text lines by default; raw bytes when using chunk mode)
- `on_last_stdout_line` — async callback per decoded stdout line
- `on_last_stdout_chunk` — async callback per raw stdout chunk
- `on_last_mace4_interpretation` — receive each completed standard `interpretation(...)` block incrementally (same incremental rules as `Mace4InterpretationBuffer`; portable list output is not supported incrementally)

`ChainResult.stream_intermediate` is `True` when the streaming executor ran. Chains that include `clausetester` use buffered execution.

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

## List of binaries

autosketches4.exe
clausefilter.exe
clausetester.exe
complex.exe
directproof.exe
dprofiles.exe
fof-prover9.exe
gen_trc_defs.exe
idfilter.exe
interpfilter.exe
interpformat.exe
isofilter
isofilter.exe
isofilter0.exe
isofilter2
isofilter2.exe
ladr_to_tptp.exe
latfilter.exe
looper
mace4.exe
miniscope.exe
mirror-flip.exe
newauto.exe
newsax.exe
olfilter.exe
perm3.exe
proof3fo.xsl
prooftrans.exe
prover9.exe
renamer.exe
rewriter.exe
sigtest.exe
test_clause_eval.exe
test_complex.exe
tptp_to_ladr.exe
unfast.exe
upper-covers.exe