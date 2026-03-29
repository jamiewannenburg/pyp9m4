"""Small end-to-end runs against resolved LADR binaries (CI downloads or ``LADR_BIN_DIR``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyp9m4.parsers import parse_prover9_output
from pyp9m4.parsers.mace4 import extract_interpretation_blocks, parse_mace4_output
from pyp9m4.resolver import BinaryResolver
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
