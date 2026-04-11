"""Tests for :mod:`pyp9m4.resolver` (no network when cache / env paths are used)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyp9m4.resolver import (
    ALL_RESOLVABLE_TOOL_NAMES,
    BinaryResolver,
    BinaryResolverError,
    CachedBinariesError,
    UnknownToolError,
    UnsupportedPlatformError,
    asset_filename_for_platform_key,
    detect_platform_key,
    normalize_resolver_tool_name,
)


def test_detect_platform_key_shape() -> None:
    key = detect_platform_key()
    assert isinstance(key, str)
    assert "-" in key


def test_asset_filename_mapping() -> None:
    assert asset_filename_for_platform_key("windows-amd64") == "ladr-windows.zip"
    assert asset_filename_for_platform_key("linux-arm64") == "ladr-linux.tar.gz"
    assert asset_filename_for_platform_key("macos-arm64") == "ladr-darwin.tar.gz"


def test_asset_filename_unknown_prefix() -> None:
    with pytest.raises(UnsupportedPlatformError):
        asset_filename_for_platform_key("freebsd-amd64")


def test_ladr_bin_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / ("prover9.exe" if os.name == "nt" else "prover9")
    exe.write_bytes(b"")
    monkeypatch.setenv("LADR_BIN_DIR", str(tmp_path))
    r = BinaryResolver(cache_root=tmp_path / "unused")
    assert r.resolve("prover9") == exe


def test_normalize_resolver_tool_name_hyphenated() -> None:
    assert normalize_resolver_tool_name("TPTP-to-LADR") == "tptp_to_ladr"


def test_unknown_tool_raises() -> None:
    with pytest.raises(UnknownToolError):
        normalize_resolver_tool_name("not_a_ladr_tool")


def test_ladr_bin_dir_resolves_hyphenated_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = "tptp_to_ladr.exe" if os.name == "nt" else "tptp_to_ladr"
    exe = tmp_path / name
    exe.write_bytes(b"")
    monkeypatch.setenv("LADR_BIN_DIR", str(tmp_path))
    r = BinaryResolver(cache_root=tmp_path / "unused")
    assert r.resolve("tptp-to-ladr") == exe


def test_ladr_bin_dir_not_a_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LADR_BIN_DIR", str(not_a_dir))
    r = BinaryResolver(cache_root=tmp_path)
    with pytest.raises(BinaryResolverError, match="LADR_BIN_DIR"):
        r.resolve("prover9")


def test_prover9_home_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "p9"
    home.mkdir()
    exe = home / ("prover9.exe" if os.name == "nt" else "prover9")
    exe.write_bytes(b"")
    monkeypatch.setenv("PROVER9_HOME", str(home))
    monkeypatch.delenv("LADR_BIN_DIR", raising=False)
    r = BinaryResolver(cache_root=tmp_path / "cache")
    assert r.resolve("prover9") == exe


def test_prover9_home_prefers_bin_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "p9"
    (home / "bin").mkdir(parents=True)
    exe = home / "bin" / ("prover9.exe" if os.name == "nt" else "prover9")
    exe.write_bytes(b"")
    (home / ("prover9.exe" if os.name == "nt" else "prover9")).write_bytes(b"wrong")
    monkeypatch.setenv("PROVER9_HOME", str(home))
    monkeypatch.delenv("LADR_BIN_DIR", raising=False)
    r = BinaryResolver(cache_root=tmp_path / "cache")
    assert r.resolve("prover9") == exe


def test_prover9_home_missing_exe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "empty"
    home.mkdir()
    monkeypatch.setenv("PROVER9_HOME", str(home))
    monkeypatch.delenv("LADR_BIN_DIR", raising=False)
    r = BinaryResolver(cache_root=tmp_path / "cache")
    with pytest.raises(CachedBinariesError, match="PROVER9_HOME"):
        r.resolve("prover9")


def test_mace4_resolves_via_cache_when_prover9_home_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mace4 is not taken from PROVER9_HOME; it uses the cached extract path."""
    home = tmp_path / "p9"
    home.mkdir()
    (home / ("prover9.exe" if os.name == "nt" else "prover9")).write_bytes(b"")
    monkeypatch.setenv("PROVER9_HOME", str(home))
    monkeypatch.delenv("LADR_BIN_DIR", raising=False)
    monkeypatch.delenv("MACE4_HOME", raising=False)
    extract = tmp_path / "fake_extract"
    extract.mkdir()
    mace = extract / ("mace4.exe" if os.name == "nt" else "mace4")
    mace.write_bytes(b"")
    r = BinaryResolver(cache_root=tmp_path / "cache")
    monkeypatch.setattr(BinaryResolver, "ensure_cached_extract", lambda self: extract)
    assert r.resolve("mace4") == mace


@pytest.mark.integration
def test_pinned_ladr_bin_contains_all_resolvable_tools() -> None:
    """Smoke: jamiewannenburg/ladr release layout matches :data:`ALL_RESOLVABLE_TOOL_NAMES`."""
    r = BinaryResolver()
    for name in sorted(ALL_RESOLVABLE_TOOL_NAMES):
        path = r.resolve(name)
        assert path.is_file(), f"missing executable for {name!r}: {path}"
