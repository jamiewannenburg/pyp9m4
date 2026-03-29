"""Resolve LADR binaries: environment overrides, cache, and GitHub release downloads."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from platformdirs import user_cache_dir

# Pinned release tag for jamiewannenburg/ladr (must match a published GitHub release).
BINARIES_VERSION: Final[str] = "v0.0.8"

_GITHUB_OWNER: Final[str] = "jamiewannenburg"
_GITHUB_REPO: Final[str] = "ladr"

# Release asset basenames follow ladr-{os}.(zip|tar.gz). Platform keys are finer-grained
# (see detect_platform_key); this table maps each key prefix to the GitHub asset file name.
_ASSET_FILENAME_BY_PREFIX: Final[dict[str, str]] = {
    "windows": "ladr-windows.zip",
    "linux": "ladr-linux.tar.gz",
    "macos": "ladr-darwin.tar.gz",
}

# Fallback SHA-256 when release metadata omits digests (GitHub currently provides them).
_PINNED_RELEASE_SHA256: Final[dict[str, str]] = {
    "ladr-darwin.tar.gz": "214662112d9044e87c36008ebb257716aefaeed58c778aefc279621f81552aa2",
    "ladr-linux.tar.gz": "8d476e27053c8fd09a748275122590600f01bda861a016217e6931673b040049",
    "ladr-windows.zip": "c969a21508cda706ce4b49e8ca16ccb208b9124143b804aeb605a1ea14bed8f8",
}

ToolName = Literal["prover9", "mace4", "interpformat", "isofilter", "prooftrans", "clausetester"]

_TOOL_STEMS: Final[dict[ToolName, str]] = {
    "prover9": "prover9",
    "mace4": "mace4",
    "interpformat": "interpformat",
    "isofilter": "isofilter",
    "prooftrans": "prooftrans",
    "clausetester": "clausetester",
}


class BinaryResolverError(Exception):
    """Base error for binary resolution."""


class UnsupportedPlatformError(BinaryResolverError):
    """No GitHub asset is defined for this OS/arch."""


class CachedBinariesError(BinaryResolverError):
    """Cached or extracted layout is missing or invalid."""


class ChecksumMismatchError(BinaryResolverError):
    """Downloaded archive SHA-256 did not match the expected value."""


def detect_platform_key() -> str:
    """Return a stable platform key (OS + normalized arch).

    Keys use ``windows-*``, ``linux-*``, or ``macos-*`` prefixes. GitHub assets are
    published per OS family (``ladr-windows.zip``, ``ladr-linux.tar.gz``, ``ladr-darwin.tar.gz``);
    use :func:`asset_filename_for_platform_key` to map a key to the release file name.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("i386", "i686"):
        arch = "x86"
    else:
        arch = machine.replace("_", "-")

    if system == "darwin":
        return f"macos-{arch}"
    if system == "windows":
        return f"windows-{arch}"
    if system == "linux":
        return f"linux-{arch}"
    return f"{system}-{arch}"


def asset_filename_for_platform_key(platform_key: str) -> str:
    """Map a :func:`detect_platform_key` value to the GitHub release asset file name."""
    if platform_key.startswith("windows"):
        return _ASSET_FILENAME_BY_PREFIX["windows"]
    if platform_key.startswith("linux"):
        return _ASSET_FILENAME_BY_PREFIX["linux"]
    if platform_key.startswith("macos"):
        return _ASSET_FILENAME_BY_PREFIX["macos"]
    raise UnsupportedPlatformError(
        f"No LADR release asset mapped for platform key {platform_key!r} "
        f"(supported prefixes: windows-, linux-, macos-)"
    )


def _exe_stem(stem: str) -> str:
    return f"{stem}.exe" if os.name == "nt" else stem


def _candidate_executable_paths(directory: Path, stem: str) -> list[Path]:
    name = _exe_stem(stem)
    return [directory / "bin" / name, directory / name]


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _release_tag_for_version(version: str) -> str:
    v = version.strip()
    if not v:
        raise ValueError("binaries version must be non-empty")
    return v if v.startswith("v") else f"v{v}"


def _github_release_url(tag: str) -> str:
    t = urllib.parse.quote(tag, safe="")
    return f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/releases/tags/{t}"


def _parse_github_digest(digest_field: str | None) -> str | None:
    if not digest_field or not isinstance(digest_field, str):
        return None
    digest_field = digest_field.strip()
    if digest_field.startswith("sha256:"):
        return digest_field.removeprefix("sha256:").strip().lower()
    return None


def _http_get_json(url: str, *, token: str | None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BinaryResolverError(f"GitHub API request failed ({e.code}): {url}") from e
    except urllib.error.URLError as e:
        raise BinaryResolverError(f"GitHub API request failed: {e.reason}") from e


def _pick_asset_metadata(
    release: dict[str, object], asset_filename: str
) -> tuple[str, str | None]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise BinaryResolverError("GitHub release JSON missing 'assets' list")
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if name != asset_filename:
            continue
        url = raw.get("browser_download_url")
        if not isinstance(url, str) or not url:
            raise BinaryResolverError(f"Asset {asset_filename!r} has no download URL")
        digest = _parse_github_digest(raw.get("digest"))  # type: ignore[arg-type]
        return url, digest
    raise BinaryResolverError(
        f"Release {release.get('tag_name')!r} has no asset named {asset_filename!r}"
    )


def _sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest().lower()


def _safe_extract_member_path(destination: Path, member_name: str) -> Path:
    """Return absolute member path; raise if it escapes ``destination``."""
    dest = destination.resolve()
    target = (dest / member_name).resolve()
    target.relative_to(dest)
    return target


def _extract_zip_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            _safe_extract_member_path(destination, name)
        zf.extractall(destination)


def _extract_tar_gz(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            _safe_extract_member_path(destination, member.name)
        tf.extractall(destination)


def _download_url_to_file(url: str, dest: Path, *, token: str | None) -> None:
    headers = {"Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)
        tmp.replace(dest)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _expected_sha256(asset_filename: str, api_digest: str | None) -> str:
    if api_digest:
        return api_digest.lower()
    pinned = _PINNED_RELEASE_SHA256.get(asset_filename)
    if not pinned:
        raise BinaryResolverError(
            f"No SHA-256 available for {asset_filename!r} "
            "(GitHub did not provide digest and there is no pinned fallback)"
        )
    return pinned.lower()


def _verify_sha256(path: Path, expected_hex: str) -> None:
    actual = _sha256_file(path)
    if actual != expected_hex.lower():
        raise ChecksumMismatchError(
            f"SHA-256 mismatch for {path.name}: expected {expected_hex}, got {actual}"
        )


def _acquire_cache_lock(lock_dir: Path, *, wait_s: float = 0.15, timeout_s: float = 600.0) -> None:
    """Best-effort cross-process lock using an exclusive directory creation."""
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / ".download-lock"
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            lock_path.mkdir()
            return
        except FileExistsError:
            if time.monotonic() > deadline:
                raise BinaryResolverError(f"Timed out waiting for cache lock: {lock_path}")
            time.sleep(wait_s)


def _release_cache_lock(lock_path: Path) -> None:
    try:
        lock_path.rmdir()
    except OSError:
        pass


@dataclass
class BinaryResolver:
    """Locate LADR executables using env overrides or a pinned GitHub release in the user cache."""

    binaries_version: str | None = None
    cache_root: Path | None = None
    platform_key: str | None = None

    def __post_init__(self) -> None:
        self._tag = _release_tag_for_version(self.binaries_version or BINARIES_VERSION)
        self._platform_key = self.platform_key or detect_platform_key()
        base = self.cache_root
        if base is None:
            base = Path(user_cache_dir("pyp9m4", appauthor=False))
        self._cache_root = base.resolve()

    @property
    def tag(self) -> str:
        return self._tag

    @property
    def resolved_platform_key(self) -> str:
        return self._platform_key

    def asset_filename(self) -> str:
        return asset_filename_for_platform_key(self._platform_key)

    def _github_token(self) -> str | None:
        return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def _extract_root(self) -> Path:
        return self._cache_root / "ladr" / self._tag / self._platform_key

    def _marker_path(self) -> Path:
        return self._extract_root() / ".pyp9m4-extracted"

    def _archive_cache_path(self, asset_filename: str) -> Path:
        return self._cache_root / "ladr" / self._tag / "_archives" / asset_filename

    def _ladr_bin_dir_from_env(self) -> Path | None:
        raw = os.environ.get("LADR_BIN_DIR")
        if not raw:
            return None
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            raise BinaryResolverError(f"LADR_BIN_DIR is not a directory: {p}")
        return p

    def _tool_home_dir(self, tool: ToolName) -> Path | None:
        env_name = {"prover9": "PROVER9_HOME", "mace4": "MACE4_HOME"}.get(tool)
        if not env_name:
            return None
        raw = os.environ.get(env_name)
        if not raw:
            return None
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            raise BinaryResolverError(f"{env_name} is not a directory: {p}")
        return p

    def ensure_cached_extract(self) -> Path:
        """Download (if needed), verify, and extract the release archive; return the extract directory."""
        if d := self._ladr_bin_dir_from_env():
            return d

        extract_root = self._extract_root()
        marker = self._marker_path()
        if marker.is_file():
            return extract_root

        asset_filename = self.asset_filename()
        archive_path = self._archive_cache_path(asset_filename)
        lock_dir = self._cache_root / "ladr" / self._tag / "_locks" / self._platform_key
        lock_token = lock_dir / ".download-lock"

        _acquire_cache_lock(lock_dir)
        try:
            if marker.is_file():
                return extract_root
            release_url = _github_release_url(self._tag)
            release_obj = _http_get_json(release_url, token=self._github_token())
            if not isinstance(release_obj, dict):
                raise BinaryResolverError("GitHub release JSON is not an object")
            release = release_obj
            download_url, api_digest = _pick_asset_metadata(release, asset_filename)
            expected = _expected_sha256(asset_filename, api_digest)

            archive_path.parent.mkdir(parents=True, exist_ok=True)
            if not archive_path.is_file():
                _download_url_to_file(download_url, archive_path, token=self._github_token())
            _verify_sha256(archive_path, expected)

            if extract_root.exists():
                shutil.rmtree(extract_root)
            extract_root.mkdir(parents=True, exist_ok=True)
            if asset_filename.endswith(".zip"):
                _extract_zip_archive(archive_path, extract_root)
            elif asset_filename.endswith(".tar.gz"):
                _extract_tar_gz(archive_path, extract_root)
            else:
                raise BinaryResolverError(f"Unsupported archive type: {asset_filename}")

            marker.write_text(
                f"pyp9m4_extract_tag={self._tag}\nasset={asset_filename}\n",
                encoding="utf-8",
            )
            return extract_root
        finally:
            _release_cache_lock(lock_token)

    def bin_directory(self) -> Path:
        """Directory containing ``prover9`` / ``mace4`` / … (uses cache download if needed)."""
        if d := self._ladr_bin_dir_from_env():
            return d
        return self.ensure_cached_extract()

    def resolve(self, tool: ToolName) -> Path:
        """Return an absolute path to the given tool, downloading into the cache if required."""
        stem = _TOOL_STEMS[tool]

        if global_bin := self._ladr_bin_dir_from_env():
            hit = _first_existing(_candidate_executable_paths(global_bin, stem))
            if hit is None:
                raise CachedBinariesError(
                    f"Executable {_exe_stem(stem)!r} not found under LADR_BIN_DIR={global_bin}"
                )
            return hit

        if tool in ("prover9", "mace4"):
            if home := self._tool_home_dir(tool):
                hit = _first_existing(_candidate_executable_paths(home, stem))
                if hit is None:
                    env = "PROVER9_HOME" if tool == "prover9" else "MACE4_HOME"
                    raise CachedBinariesError(
                        f"Executable {_exe_stem(stem)!r} not found under {env}={home}"
                    )
                return hit

        root = self.ensure_cached_extract()
        hit = _first_existing(_candidate_executable_paths(root, stem))
        if hit is None:
            raise CachedBinariesError(
                f"Executable {_exe_stem(stem)!r} not found under extracted LADR root {root}"
            )
        return hit
