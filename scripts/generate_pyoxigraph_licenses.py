#!/usr/bin/env python3
"""Regenerate docker/licenses/pyoxigraph-THIRD-PARTY.txt.

    uv run python scripts/generate_pyoxigraph_licenses.py

The pyoxigraph wheel ships no licence files, yet its extension module is
compiled from about 200 Rust crates and from RocksDB and LZ4, which are C++
and C. The container image redistributes that module, so it has to carry
their terms: for the MIT, ISC, BSD and Unicode licences that means each
crate's own copyright line, which no generic text has.

Run this whenever uv.lock moves pyoxigraph to another version;
tests/test_third_party_notices.py fails until it has been. It needs git and
Docker, and installs nothing on this machine:

* Oxigraph is cloned at the tag of the locked version, with the RocksDB and
  LZ4 submodules that oxrocksdb-sys compiles.
* cargo-about, in a pinned Rust container, collects the licence text of every
  crate the pyoxigraph crate depends on for all targets, with the features the
  wheel is built with and without build or dev dependencies, using
  scripts/pyoxigraph-licenses/about.toml and about.hbs.
* RocksDB and LZ4 are not crates, so cargo-about does not see them. They are
  added from the submodules: LevelDB's licence, LZ4's, and every comment block
  in a compiled RocksDB file (or a header it includes) that names a copyright
  holder other than RocksDB's and LevelDB's authors.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "scripts" / "pyoxigraph-licenses"
OUTPUT = REPO / "docker" / "licenses" / "pyoxigraph-THIRD-PARTY.txt"

UPSTREAM = "https://github.com/oxigraph/oxigraph"
RUST_IMAGE = "rust:1.99.1"
CARGO_ABOUT = "0.9.3"

#: The authors RocksDB's own licence covers, and LevelDB's, whose licence is
#: carried in full; any other copyright holder gets its notice reproduced.
_OWN_AUTHORS = re.compile(r"facebook|meta platforms|leveldb authors", re.IGNORECASE)
_RULE = "=" * 80


def main() -> int:
    version = _locked_version()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "oxigraph"
        _checkout(version, source)
        crates = _crate_licences(source)
        compiled = _compiled_c_notices(source)
    OUTPUT.write_text(
        _header(version) + crates.rstrip() + "\n\n" + compiled, encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)} for pyoxigraph {version}")
    return 0


def _locked_version() -> str:
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    (version,) = {p["version"] for p in lock["package"] if p["name"] == "pyoxigraph"}
    return version


def _checkout(version: str, into: Path) -> None:
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "-q", "--depth", "1"]
        + ["--branch", f"v{version}", UPSTREAM]
        + [str(into)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(into), "-c", "advice.detachedHead=false", "submodule"]
        + ["update", "-q", "--init", "--depth", "1"]
        + ["oxrocksdb-sys/rocksdb", "oxrocksdb-sys/lz4"],
        check=True,
    )


def _crate_licences(source: Path) -> str:
    script = (
        f"cargo install cargo-about --version {CARGO_ABOUT} --locked"
        " --features cli --quiet"
        " && cd /src && cargo about generate --locked"
        " --config /config/about.toml --manifest-path python/Cargo.toml"
        " /config/about.hbs"
    )
    done = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{source}:/src:ro"]
        + ["-v", f"{CONFIG}:/config:ro", RUST_IMAGE, "bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _compiled_c_notices(source: Path) -> str:
    sys_crate = source / "oxrocksdb-sys"
    rocksdb = sys_crate / "rocksdb"
    notices: dict[str, list[str]] = {}
    for name in sorted(_compiled_rocksdb_files(rocksdb)):
        for block in _comment_blocks(rocksdb / name):
            holders = re.findall(r"(?i)copyright[^\n]*", block)
            if any(not _OWN_AUTHORS.search(h) for h in holders):
                notices.setdefault(block, []).append(name)
    parts = [
        _RULE,
        "C and C++ code compiled into oxrocksdb-sys",
        "",
        "oxrocksdb-sys compiles RocksDB and the LZ4 library into the module.",
        "",
        "RocksDB is offered under GPL-2.0-only or Apache-2.0 and is redistributed",
        "here under Apache-2.0, whose text is above. It contains code from",
        "LevelDB, under the licence below, and files with notices of their own,",
        "reproduced after it.",
        "",
        _RULE,
        "RocksDB: LICENSE.leveldb",
        "",
        (rocksdb / "LICENSE.leveldb").read_text(encoding="utf-8").strip(),
    ]
    for block, files in notices.items():
        parts += ["", _RULE, "RocksDB: " + ", ".join(files), "", block]
    parts += [
        "",
        _RULE,
        "LZ4 library (lz4/lib)",
        "",
        (sys_crate / "lz4" / "lib" / "LICENSE").read_text(encoding="utf-8").strip(),
    ]
    return "\n".join(parts) + "\n"


def _compiled_rocksdb_files(rocksdb: Path) -> set[str]:
    """The sources oxrocksdb-sys's build.rs compiles (LIB_SOURCES in
    src.mk) and every header they include from the tree, transitively."""
    makefile = (rocksdb / "src.mk").read_text(encoding="utf-8")
    listed = makefile.split("LIB_SOURCES =", 1)[1].split("ifeq", 1)[0]
    files = {p.strip() for p in listed.split("\\") if (rocksdb / p.strip()).is_file()}
    pending = list(files)
    include = re.compile(r'#include\s+"([^"]+)"')
    while pending:
        path = rocksdb / pending.pop()
        for header in include.findall(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            for candidate in (header, str(path.parent.relative_to(rocksdb) / header)):
                if (rocksdb / candidate).is_file():
                    if candidate not in files:
                        files.add(candidate)
                        pending.append(candidate)
                    break
            else:
                if (rocksdb / "include" / header).is_file():
                    candidate = f"include/{header}"
                    if candidate not in files:
                        files.add(candidate)
                        pending.append(candidate)
    return files


#: A ``/* ... */`` comment, or a run of ``//`` lines.
_COMMENT = re.compile(r"/\*.*?\*/|(?:^[ \t]*//[^\n]*\n?)+", re.DOTALL | re.MULTILINE)


def _comment_blocks(path: Path) -> list[str]:
    """Every comment in a file. A third-party notice is not always at the
    top: xxhash.h has RocksDB's own changes, preprocessor lines included,
    before it."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [block.strip() for block in _COMMENT.findall(text)]


def _header(version: str) -> str:
    accepted = re.findall(
        r'^\s*"([^"]+)",',
        (CONFIG / "about.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return "\n".join(
        [
            f"Third-party licences in pyoxigraph {version}",
            "",
            "The pyoxigraph wheel ships no licence files. These are the terms of the",
            "code compiled into its extension module, which the OrionBelt Ontology",
            "Builder container image redistributes: first the Rust crates, then the",
            "C and C++ code of RocksDB and LZ4.",
            "",
            "Generated by scripts/generate_pyoxigraph_licenses.py from Oxigraph's",
            f"Cargo.lock and submodules at tag v{version}, with cargo-about {CARGO_ABOUT}.",
            *textwrap.wrap(
                "Do not edit by hand. Where a crate offers a choice of licence, it"
                " is listed under the first of: " + ", ".join(accepted) + ".",
                width=76,
            ),
            "",
            "",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
