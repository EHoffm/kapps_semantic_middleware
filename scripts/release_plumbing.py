#!/usr/bin/env python3
"""What both release drivers need and neither owns (#129).

`prepare_release.py` and `publish_release.py` are two halves of one mechanism with a human
review between them, so they keep arriving at the same three problems: where the repo root is,
how a script reports a violation to the person running it, and how a tree at a given revision
reaches a directory. Each was written twice, and the second copy of `export_tree` lost the
comment explaining why the extraction is done with the standard library -- which is the whole
reason the code looks the way it does.

This module never ships. `release_allowlist.RULES` excludes `scripts/` wholesale, and
`release_checks.py` -- the one file out of `scripts/` that does ship -- deliberately imports
nothing, this module included.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Iterable

GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
"""The dev checkout this script was run from. Every release script lives in `scripts/`."""


def print_violations(violations: Iterable[object]) -> None:
    """Print every hygiene violation to stderr, one actionable line each.

    Takes the whole list rather than the first: one fix per run would make a five-violation
    tree take five runs to clear. Typed loosely because `release_checks.Violation` is a
    NamedTuple this module must not import -- the dependency runs the other way.
    """
    for violation in violations:
        print(
            f"  {violation.check}  {violation.path}  {violation.detail}",  # type: ignore[attr-defined]
            file=sys.stderr,
        )


def export_tree(repo: Path, revision: str, destination: Path) -> None:
    """Extract ``repo``'s tree at ``revision`` into ``destination``.

    `git archive` gives exactly the tracked files at that commit, with no `.git` and no
    untracked residue -- a stray local file cannot reach a release however messy the checkout
    is.

    ``repo`` is passed rather than defaulted to `REPO_ROOT`: a default argument binds the real
    checkout at import time, which silently defeats the one seam the release tests have --
    they point the driver at a throwaway repository by rebinding its `REPO_ROOT`.

    Extracted with the stdlib rather than an external `tar`, which Windows has no guarantee of.
    Map #108 makes Windows first-class for everything a user touches, and a release mechanism
    that dies before its first hygiene check is the worst place to discover a missing tool.
    """
    archive_proc = subprocess.run(
        ["git", "-C", str(repo), "archive", revision],
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout), mode="r|") as archive:
        archive.extractall(destination, filter="data")
