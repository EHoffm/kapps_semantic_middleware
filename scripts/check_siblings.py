#!/usr/bin/env python3
"""Check that the sibling checkouts match `siblings.lock.toml`.

Run this first when something fails in a way the code does not explain. Root ADR 0001 wires the
three siblings as editable *path* dependencies, so `uv.lock` records where each one is and nothing
about which commit is in it -- every machine imports whatever its local checkout happens to hold,
and each wrong commit fails differently.

    python scripts/check_siblings.py

Exit code 0 if every sibling matches, 1 otherwise. Nothing is modified.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / "siblings.lock.toml"

GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)


def git(checkout: Path, *args: str) -> str | None:
    """Run a git command in `checkout`, or return None if it cannot."""
    try:
        done = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return done.stdout.strip()


def check(name: str, spec: dict) -> list[str]:
    """Return a list of problems with this sibling. Empty means it is fine."""
    checkout = (REPO_ROOT / spec["path"]).resolve()
    problems: list[str] = []

    if not (checkout / ".git").exists():
        return [f"not a git checkout at {checkout}"]

    head = git(checkout, "rev-parse", "--short", "HEAD")
    wanted = spec["commit"]
    # Compare at the shorter of the two lengths: `rev-parse --short` picks its own width based on
    # how much is needed to stay unambiguous in that repo, and it grows as a repo does. Comparing
    # the raw strings would start failing on a busy sibling for no real reason.
    if head and not (head.startswith(wanted) or wanted.startswith(head)):
        problems.append(f"at {head}, want {wanted}")

    branch = git(checkout, "branch", "--show-current")
    if branch != spec["branch"]:
        problems.append(f"on branch {branch or '(detached)'}, want {spec['branch']}")

    if git(checkout, "status", "--porcelain"):
        problems.append("working tree is dirty (uncommitted changes are invisible to everyone else)")

    # The commit existing locally is not enough -- a teammate has to be able to fetch it.
    upstream = git(checkout, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream is None:
        problems.append("branch has no upstream, so nobody else can obtain this commit")
    else:
        unpushed = git(checkout, "rev-list", "--count", "@{u}..HEAD")
        if unpushed and unpushed != "0":
            problems.append(
                f"{unpushed} unpushed commit(s) -- this checkout cannot be reproduced elsewhere "
                f"until they are pushed to {upstream}"
            )

    return problems


def main() -> int:
    if not LOCK.exists():
        print(f"{RED}missing {LOCK}{OFF}", file=sys.stderr)
        return 1

    siblings = tomllib.loads(LOCK.read_text())
    failed = {}

    print(f"\n{BOLD}Sibling checkouts, against siblings.lock.toml{OFF}\n")
    for name, spec in siblings.items():
        problems = check(name, spec)
        if problems:
            failed[name] = spec
            print(f"  {RED}✗ {name}{OFF}")
            for problem in problems:
                print(f"      {problem}")
        else:
            print(f"  {GREEN}✓ {name}{OFF}  {DIM}{spec['branch']} @ {spec['commit']}{OFF}")

    if not failed:
        print(f"\n{GREEN}All siblings match.{OFF}\n")
        return 0

    print(f"\n{YELLOW}To fix:{OFF}")
    for name, spec in failed.items():
        print(f"\n  # {name}")
        print(f"  git -C {spec['path']} fetch {spec['remote']}")
        print(f"  git -C {spec['path']} checkout {spec['branch']}")
    print("\n  uv sync\n")
    print(f"{DIM}Why each pin is what it is: see SIBLINGS.md{OFF}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
