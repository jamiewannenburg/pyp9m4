# pyp9m4

Python wrapper for **Prover9**, **Mace4**, and related [LADR](https://www.cs.unm.edu/~mccune/mace4/) command-line tools. It resolves pinned binaries (or your own install), runs them via **asyncio** with sync helpers for scripts and notebooks, exposes hand-curated CLI option types, and includes parsers for common output shapes.

- **Python**: 3.10+
- **License**: GPL-2.0 (wrapper; downloaded binaries are separate artifacts)

## Installation

```bash
pip install pyp9m4
```

For development and tests:

```bash
pip install -e ".[dev]"
```

Optional bridges (see `pyproject.toml`):

```bash
pip install "pyp9m4[smt]"   # PySMT-related helpers
```

## Resolving binaries

By default, `BinaryResolver` downloads a **pinned** release from [jamiewannenburg/ladr](https://github.com/jamiewannenburg/ladr) into the user cache (via `platformdirs`). You can override with:

| Variable | Effect |
|----------|--------|
| `LADR_BIN_DIR` | Directory containing `prover9`, `mace4`, etc. (highest priority) |
| `PROVER9_HOME` / `MACE4_HOME` | Install roots for those two tools |
| `GITHUB_TOKEN` or `GH_TOKEN` | Optional, for GitHub API rate limits when downloading |

The pinned tag is exposed as `pyp9m4.BINARIES_VERSION`.

## Quick start (sync)

```python
from pathlib import Path

from pyp9m4 import BinaryResolver, SubprocessInvocation, RunStatus, run_sync
from pyp9m4.options import Prover9CliOptions
from pyp9m4.parsers import parse_prover9_output

resolver = BinaryResolver()
prover9 = resolver.resolve("prover9")

opts = Prover9CliOptions(input_files=(str(Path("problem.in")),))
inv = SubprocessInvocation(
    argv=(str(prover9), *opts.to_argv()),
    timeout_s=120,
)
result = run_sync(inv)

assert result.status == RunStatus.SUCCEEDED
parsed = parse_prover9_output(result.stdout)
print(parsed.statistics)
print(parsed.proof_segments[0].text[:500])
```

`run_sync` is safe from **Jupyter/IPython** when an event loop is already running (it runs the async work on a helper thread).

## Typed CLI options

Each tool has a dataclass with a `to_argv()` method that returns fragments **after** the executable name (see `pyp9m4.options`):

- `Prover9CliOptions`
- `Mace4CliOptions`
- `InterpformatCliOptions`
- `IsofilterCliOptions`
- `ProofTransCliOptions`

Build `argv` as `(str(executable), *options.to_argv(), ...)` and pass it to `SubprocessInvocation`.

## Async usage

```python
import asyncio
from pyp9m4 import AsyncToolRunner, BinaryResolver, SubprocessInvocation

async def main():
    p9 = BinaryResolver().resolve("prover9")
    inv = SubprocessInvocation(argv=(str(p9), "-h"))
    result = await AsyncToolRunner().run(inv)
    print(result.exit_code, result.stdout[:200])

asyncio.run(main())
```

Streaming (line-level events):

```python
from pyp9m4 import AsyncToolRunner, SubprocessInvocation

async def drain():
    inv = SubprocessInvocation(argv=(str(BinaryResolver().resolve("prover9")), "-h"))
    async for event in AsyncToolRunner().stream_events(inv):
        print(event)

# asyncio.run(drain())
```

For synchronous code, `stream_events_sync(inv)` collects all events into a list (fine for small outputs).

## Parsers

- `parse_prover9_output(stdout)` → statistics, proof segments, warnings
- `parse_mace4_output(stdout)` → interpretations / models
- `parse_pipeline_tool_output`, `inspect_pipeline_text` for lighter pipeline tools

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
