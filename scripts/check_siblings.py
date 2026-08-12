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


def same_commit(a: str, b: str) -> bool:
    """True if two shas name the same commit, whatever width each is abbreviated to.

    `rev-parse --short` picks its own width from how much is needed to stay unambiguous in that
    repository, and that grows as the repository does. Comparing the raw strings would start
    failing on a busy sibling for no real reason.
    """
    return a.startswith(b) or b.startswith(a)


def check(name: str, spec: dict) -> list[str]:
    """Return a list of problems with this sibling. Empty means it is fine."""
    checkout = (REPO_ROOT / spec["path"]).resolve()
    problems: list[str] = []

    if not (checkout / ".git").exists():
        return [f"not a git checkout at {checkout}"]

    head = git(checkout, "rev-parse", "--short", "HEAD")
    wanted = spec["commit"]
    if head and not same_commit(head, wanted):
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


def repair(name: str, spec: dict, checkout: Path) -> list[str]:
    """The lines to print about a failed sibling: commands that work, or why none would.

    This used to be two unconditional lines -- fetch, then check the branch out -- which are the
    right answer only when the pin *is* the branch tip. When the branch has moved past the pin,
    checking it out lands on the tip and the check stays red, now reporting a different sha
    (#152, and it cost real time during #146). A tool that prints an instruction it will then
    reject teaches the reader to stop believing it, so each case says what it can honestly say.

    `spec["path"]` is what goes into the printed commands, because that is the relative path the
    developer types; `checkout` is the resolved one this function interrogates.
    """
    lines = [f"  # {name}"]
    path, branch, remote, pin = spec["path"], spec["branch"], spec["remote"], spec["commit"]

    if not (checkout / ".git").exists():
        return lines + [f"  # no checkout at {checkout} -- clone it. See SIBLINGS.md."]

    # Where `fetch` + `checkout <branch>` + `pull --ff-only` actually ends up. The remote-tracking
    # ref is the honest target where it exists: it is what a teammate obtains, and a bare
    # `checkout` of an existing local branch does not fast-forward, so the local ref can lie.
    tip = git(checkout, "rev-parse", "--short", f"{remote}/{branch}") or git(
        checkout, "rev-parse", "--short", branch
    )
    if tip is None:
        return lines + [f"  # branch {branch} is unknown in this checkout. See SIBLINGS.md."]

    if git(checkout, "rev-parse", "--verify", "--quiet", f"{pin}^{{commit}}") is None:
        # Absent locally, which a fetch may well cure -- so this is the one case where the old
        # advice is still exactly right, plus a note on what it means if it does not help.
        return lines + [
            f"  git -C {path} fetch {remote}",
            f"  git -C {path} checkout {branch}",
            f"  git -C {path} pull --ff-only",
            f"  # {pin} is not in this checkout. If it is still missing after the fetch, whoever",
            "  #   recorded it never pushed it, and nobody else can reach it either.",
        ]

    if same_commit(pin, tip):
        return lines + [
            f"  git -C {path} fetch {remote}",
            f"  git -C {path} checkout {branch}",
            f"  git -C {path} pull --ff-only",
        ]

    # `merge-base --is-ancestor` reports through its exit code and prints nothing, so `git()`
    # returning "" means yes and None means no. Equality is settled above, since a commit is its
    # own ancestor and would otherwise land here.
    if git(checkout, "merge-base", "--is-ancestor", pin, tip) is not None:
        return lines + [
            f"  # {branch} has moved past the pin.",
            f"  #   {remote}/{branch} is at {tip}; the lock wants {pin}.",
            "  # No checkout reaches the pin, so nothing you do to this working tree makes this",
            "  #   green -- the lock is what is out of date, not the checkout.",
            "  # Advance it in siblings.lock.toml, with a line in `why` saying what moved:",
            f'  #     commit = "{tip}"',
            f"  # If those commits are unwanted instead, reset {branch} to {pin} and force-push.",
        ]

    return lines + [
        f"  # {pin} is not on {branch} at all ({remote}/{branch} is at {tip}), so no checkout",
        "  #   reaches it. Either the branch was rewritten, or the pin names a commit from",
        "  #   somewhere else. Settle which, then correct siblings.lock.toml. See SIBLINGS.md.",
    ]


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
        print()
        for line in repair(name, spec, (REPO_ROOT / spec["path"]).resolve()):
            print(line)
    # Changing a sibling checkout changes what uv resolves against, so the sync is part of the
    # repair rather than an afterthought -- and if it rewrites `uv.lock`, that change is real and
    # belongs in a commit. SIBLINGS.md explains why (#152).
    print("\n  uv sync\n")
    print(f"{DIM}Why each pin is what it is: see SIBLINGS.md{OFF}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
