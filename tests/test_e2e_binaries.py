"""Small end-to-end runs against resolved LADR binaries (CI downloads or ``LADR_BIN_DIR``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyp9m4 import Mace4, Prover9, ProverOutcome
from pyp9m4.options.prover9 import Prover9CliOptions
from pyp9m4.parsers import parse_prover9_output
from pyp9m4.parsers.mace4 import extract_interpretation_blocks, parse_mace4_output
from pyp9m4.resolver import BinaryResolver, CachedBinariesError
from pyp9m4.runner import RunStatus, SubprocessInvocation, run_sync

_CORPUS = Path(__file__).resolve().parent / "corpus" / "e2e"


@pytest.fixture
def resolver() -> BinaryResolver:
    return BinaryResolver()


@pytest.mark.integration
def test_e2e_prover9_trivial_theorem(resolver: BinaryResolver) -> None:
    p9 = resolver.resolve("prover9")
    inp = _CORPUS / "trivial.in"
    res = run_sync(SubprocessInvocation(argv=(str(p9), "-f", str(inp)), timeout_s=120))
    assert res.status == RunStatus.SUCCEEDED
    assert res.exit_code == 0
    assert "THEOREM PROVED" in res.stdout
    parsed = parse_prover9_output(res.stdout)
    assert parsed.statistics.get("proofs") == "1"
    assert len(parsed.proof_segments) >= 1


@pytest.mark.integration
def test_e2e_mace4_finds_model(resolver: BinaryResolver) -> None:
    m4 = resolver.resolve("mace4")
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    res = run_sync(SubprocessInvocation(argv=(str(m4), "-n", "2"), stdin=text, timeout_s=120))
    assert res.status == RunStatus.SUCCEEDED
    assert "MODEL" in res.stdout
    parsed = parse_mace4_output(res.stdout)
    assert len(parsed.interpretations) >= 1
    assert parsed.interpretations[0].domain_size == 2


@pytest.mark.integration
def test_e2e_prooftrans_accepts_prover9_stdout(resolver: BinaryResolver) -> None:
    p9 = resolver.resolve("prover9")
    pt = resolver.resolve("prooftrans")
    inp = _CORPUS / "trivial.in"
    r1 = run_sync(SubprocessInvocation(argv=(str(p9), "-f", str(inp)), timeout_s=120))
    assert r1.status == RunStatus.SUCCEEDED
    r2 = run_sync(SubprocessInvocation(argv=(str(pt),), stdin=r1.stdout, timeout_s=120))
    assert r2.status == RunStatus.SUCCEEDED
    assert r2.exit_code == 0
    assert "PROOF" in r2.stdout or "proof" in r2.stdout.lower()


@pytest.mark.integration
def test_e2e_interpformat_portable_from_mace4(resolver: BinaryResolver) -> None:
    m4 = resolver.resolve("mace4")
    ifc = resolver.resolve("interpformat")
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    r1 = run_sync(SubprocessInvocation(argv=(str(m4), "-n", "2"), stdin=text, timeout_s=120))
    assert r1.status == RunStatus.SUCCEEDED
    r2 = run_sync(SubprocessInvocation(argv=(str(ifc), "portable"), stdin=r1.stdout, timeout_s=120))
    assert r2.status == RunStatus.SUCCEEDED
    assert r2.exit_code == 0
    assert "[" in r2.stdout and "]" in r2.stdout


@pytest.mark.integration
def test_e2e_prover9_facade_run(resolver: BinaryResolver) -> None:
    """Smoke: high-level Prover9.run against resolved prover9 binary."""
    inp = _CORPUS / "trivial.in"
    p9 = Prover9(resolver=resolver, timeout_s=120)
    result = p9.run(options=Prover9CliOptions(input_files=(str(inp),)))
    assert result.lifecycle == "succeeded"
    assert result.exit_code == 0
    assert result.outcome == ProverOutcome.proved
    assert "THEOREM PROVED" in result.stdout
    assert result.parsed.statistics.get("proofs") == "1"


@pytest.mark.integration
def test_e2e_mace4_facade_models(resolver: BinaryResolver) -> None:
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    m4 = Mace4(resolver=resolver, domain_size=2, timeout_s=120)
    models = list(m4.models(text))
    assert len(models) >= 1
    assert models[0].domain_size == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_e2e_mace4_start_amodels_status(resolver: BinaryResolver) -> None:
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    m4 = Mace4(resolver=resolver, domain_size=2, timeout_s=120)
    handle = m4.start_amodels(text)
    snap0 = await handle.status()
    assert snap0.lifecycle in ("pending", "running", "succeeded")
    await handle.wait()
    final = await handle.status()
    assert final.lifecycle == "succeeded"
    assert final.models_found >= 1
    got = [m async for m in handle.amodels()]
    assert len(got) >= 1


@pytest.mark.integration
def test_e2e_mace4_facade_eliminate_isomorphic(resolver: BinaryResolver) -> None:
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    m4 = Mace4(resolver=resolver, domain_size=2, timeout_s=120)
    models = list(m4.models(text, eliminate_isomorphic=True))
    assert isinstance(models, list)


@pytest.mark.integration
def test_e2e_clausetester_on_mace4_interpretation(resolver: BinaryResolver) -> None:
    try:
        resolver.resolve("clausetester")
    except CachedBinariesError:
        pytest.skip("clausetester not available in resolved LADR bundle")
    m4 = resolver.resolve("mace4")
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    r1 = run_sync(SubprocessInvocation(argv=(str(m4), "-n", "2"), stdin=text, timeout_s=120))
    assert r1.status == RunStatus.SUCCEEDED
    parsed = parse_mace4_output(r1.stdout)
    assert len(parsed.interpretations) >= 1
    mi = parsed.interpretations[0]
    r2 = mi.test_clause("P(a).\n", resolver=resolver, timeout_s=120)
    assert r2.status == RunStatus.SUCCEEDED


@pytest.mark.integration
def test_e2e_isofilter_accepts_interpretation(resolver: BinaryResolver) -> None:
    m4 = resolver.resolve("mace4")
    iso = resolver.resolve("isofilter")
    text = (_CORPUS / "mace4_sat.in").read_text(encoding="utf-8")
    r1 = run_sync(SubprocessInvocation(argv=(str(m4), "-n", "2"), stdin=text, timeout_s=120))
    assert r1.status == RunStatus.SUCCEEDED
    blocks = extract_interpretation_blocks(r1.stdout)
    assert len(blocks) >= 1
    body = blocks[0].rstrip()
    if not body.endswith("."):
        body += "."
    r2 = run_sync(SubprocessInvocation(argv=(str(iso),), stdin=body, timeout_s=120))
    assert r2.status == RunStatus.SUCCEEDED
    assert r2.exit_code == 0
