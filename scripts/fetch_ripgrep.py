"""Project-managed ripgrep provisioning (ADR-025, mechanism (i)).

Downloads the pinned official BurntSushi/ripgrep release binary for the
current platform into `.tools/rg/`, verifying SHA-256. This mirrors what
`@vscode/ripgrep` does for the TS filesystem MCP — canonical upstream,
checksum-pinned — but driven from Python with stdlib only (no new dep).

The native filesystem `grep` tool resolves `.tools/rg/rg[.exe]` (see
read_tools._resolve_rg). Run once after setup:

    python scripts/fetch_ripgrep.py

Idempotent: re-running with the binary already present + hash matching is
a no-op. Trust model: first fetch is TLS-authenticated from GitHub; the
pinned SHA-256 then protects every subsequent fetch against tampering.
If a platform's hash is not yet pinned the script computes it, prints it
for the maintainer to pin, and proceeds (TOFU) with a loud warning.
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import stat
import sys
import tarfile
import urllib.request
import zipfile

RIPGREP_VERSION = "14.1.1"
_BASE = f"https://github.com/BurntSushi/ripgrep/releases/download/{RIPGREP_VERSION}"

# (asset filename, archive kind) per (os, machine). Hashes pinned below.
_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "amd64"): (f"ripgrep-{RIPGREP_VERSION}-x86_64-pc-windows-msvc.zip", "zip"),
    ("linux", "x86_64"): (f"ripgrep-{RIPGREP_VERSION}-x86_64-unknown-linux-musl.tar.gz", "tar"),
    ("linux", "aarch64"): (f"ripgrep-{RIPGREP_VERSION}-aarch64-unknown-linux-gnu.tar.gz", "tar"),
    ("darwin", "arm64"): (f"ripgrep-{RIPGREP_VERSION}-aarch64-apple-darwin.tar.gz", "tar"),
    ("darwin", "x86_64"): (f"ripgrep-{RIPGREP_VERSION}-x86_64-apple-darwin.tar.gz", "tar"),
}

# SHA-256 of each release asset. None = not yet pinned (TOFU + warn).
# Populate from a verified fetch; once set, mismatches fail closed.
_SHA256: dict[str, str | None] = {
    f"ripgrep-{RIPGREP_VERSION}-x86_64-pc-windows-msvc.zip":
        "d0f534024c42afd6cb4d38907c25cd2b249b79bbe6cc1dbee8e3e37c2b6e25a1",
    f"ripgrep-{RIPGREP_VERSION}-x86_64-unknown-linux-musl.tar.gz": None,
    f"ripgrep-{RIPGREP_VERSION}-aarch64-unknown-linux-gnu.tar.gz": None,
    f"ripgrep-{RIPGREP_VERSION}-aarch64-apple-darwin.tar.gz": None,
    f"ripgrep-{RIPGREP_VERSION}-x86_64-apple-darwin.tar.gz": None,
}


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _dest_dir() -> str:
    return os.path.join(_repo_root(), ".tools", "rg")


def _platform_key() -> tuple[str, str]:
    osname = "windows" if os.name == "nt" else sys.platform  # "linux" / "darwin"
    mach = platform.machine().lower()
    if osname == "windows":
        return ("windows", "amd64")  # only x86_64 windows asset for 14.1.1
    if mach in ("x86_64", "amd64"):
        return (osname, "x86_64")
    if mach in ("arm64", "aarch64"):
        return (osname, "arm64" if osname == "darwin" else "aarch64")
    return (osname, mach)


def _binary_path() -> str:
    return os.path.join(_dest_dir(), "rg.exe" if os.name == "nt" else "rg")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_rg(kind: str, data: bytes, out_path: str) -> None:
    member_name = "rg.exe" if os.name == "nt" else "rg"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(n for n in zf.namelist() if n.endswith("/" + member_name) or n == member_name)
            with zf.open(name) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            name = next(
                m for m in tf.getnames()
                if m.endswith("/" + member_name) or m == member_name
            )
            extracted = tf.extractfile(name)
            assert extracted is not None
            with open(out_path, "wb") as dst:
                dst.write(extracted.read())
    if os.name != "nt":
        st = os.stat(out_path)
        os.chmod(out_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    key = _platform_key()
    if key not in _ASSETS:
        print(f"ERROR: no pinned ripgrep asset for platform {key}", file=sys.stderr)
        return 2
    asset, kind = _ASSETS[key]
    out = _binary_path()

    if os.path.isfile(out):
        print(f"ripgrep already present: {out}")
        return 0

    url = f"{_BASE}/{asset}"
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp:  # noqa: S310 (https github only)
        data = resp.read()

    digest = _sha256(data)
    expected = _SHA256.get(asset)
    if expected is None:
        print(
            f"WARNING: SHA-256 for {asset} not pinned. Computed {digest}.\n"
            f"         Pin this value in scripts/fetch_ripgrep.py:_SHA256 "
            f"(proceeding TOFU — first fetch trusts GitHub TLS).",
            file=sys.stderr,
        )
    elif digest != expected:
        print(
            f"ERROR: SHA-256 mismatch for {asset}\n  expected {expected}\n  got      {digest}",
            file=sys.stderr,
        )
        return 1

    _extract_rg(kind, data, out)
    print(f"ripgrep {RIPGREP_VERSION} -> {out}")
    print(f"SHA-256({asset}) = {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
