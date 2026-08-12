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
from typing import NamedTuple

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


class Problem(NamedTuple):
    """One thing wrong with a sibling checkout.

    `kind` exists so `repair` can answer the problem that actually fired instead of inferring one
    from the shas. Getting that wrong is not a cosmetic slip: a dirty tree sitting exactly on the
    pin would otherwise draw a confident paragraph about the lock being out of date, and the
    uncommitted change -- the only real complaint -- would go unmentioned.
    """

    kind: str
    """One of: missing, commit, branch, dirty, unpushed."""

    detail: str
    """The line shown under the sibling's name."""


def check(name: str, spec: dict) -> list[Problem]:
    """Return a list of problems with this sibling. Empty means it is fine."""
    checkout = (REPO_ROOT / spec["path"]).resolve()
    problems: list[Problem] = []

    if not (checkout / ".git").exists():
        return [Problem("missing", f"not a git checkout at {checkout}")]

    head = git(checkout, "rev-parse", "--short", "HEAD")
    wanted = spec["commit"]
    if head and not same_commit(head, wanted):
        problems.append(Problem("commit", f"at {head}, want {wanted}"))

    branch = git(checkout, "branch", "--show-current")
    if branch != spec["branch"]:
        problems.append(
            Problem("branch", f"on branch {branch or '(detached)'}, want {spec['branch']}")
        )

    if git(checkout, "status", "--porcelain"):
        problems.append(
            Problem("dirty", "working tree is dirty (uncommitted changes are invisible to everyone else)")
        )

    # The commit existing locally is not enough -- a teammate has to be able to fetch it.
    upstream = git(checkout, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream is None:
        problems.append(
            Problem("unpushed", "branch has no upstream, so nobody else can obtain this commit")
        )
    else:
        unpushed = git(checkout, "rev-list", "--count", "@{u}..HEAD")
        if unpushed and unpushed != "0":
            problems.append(
                Problem(
                    "unpushed",
                    f"{unpushed} unpushed commit(s) -- this checkout cannot be reproduced "
                    f"elsewhere until they are pushed to {upstream}",
                )
            )

    return problems


def onto_the_pin(path: str, branch: str, remote: str) -> list[str]:
    """The three commands that move a checkout onto its branch tip.

    `pull --ff-only` is not decoration: a bare `checkout` of an existing local branch does not
    fast-forward, so fetch-then-checkout alone leaves you on whatever that ref held last time.
    """
    return [
        f"  git -C {path} fetch {remote}",
        f"  git -C {path} checkout {branch}",
        f"  git -C {path} pull --ff-only",
    ]


def pin_advice(spec: dict, checkout: Path) -> list[str]:
    """What to do about a checkout whose commit or branch does not match the pin.

    This used to be two unconditional lines -- fetch, then check the branch out -- which are the
    right answer only when the pin *is* the branch tip. When the branch has moved past the pin,
    checking it out lands on the tip and the check stays red, now reporting a different sha
    (#152, and it cost real time during #146). A tool that prints an instruction it will then
    reject teaches the reader to stop believing it, so each case says what it can honestly say.
    """
    path, branch, remote, pin = spec["path"], spec["branch"], spec["remote"], spec["commit"]

    # Where a fetch, a checkout and a fast-forward would land. The remote-tracking ref is the
    # honest target where it exists, because it is what a teammate obtains. It is only ever as
    # fresh as the last fetch, though, which is why every branch below either fetches first or
    # says which sha it is quoting.
    tip = git(checkout, "rev-parse", "--short", f"{remote}/{branch}") or git(
        checkout, "rev-parse", "--short", branch
    )
    if tip is None:
        return [f"  # branch {branch} is unknown in this checkout. See SIBLINGS.md."]

    if git(checkout, "rev-parse", "--verify", "--quiet", f"{pin}^{{commit}}") is None:
        # Absent locally, which a fetch may well cure -- so this is the one case where the old
        # advice is still exactly right, plus a note on what it means if it does not help.
        return onto_the_pin(path, branch, remote) + [
            f"  # {pin} is not in this checkout. If it is still missing after the fetch, whoever",
            "  #   recorded it never pushed it, and nobody else can reach it either.",
        ]

    if same_commit(pin, tip):
        return onto_the_pin(path, branch, remote)

    # `merge-base --is-ancestor` reports through its exit code and prints nothing, so `git()`
    # returning "" means yes and None means no. Equality is settled above, since a commit is its
    # own ancestor and would otherwise land here.
    if git(checkout, "merge-base", "--is-ancestor", pin, tip) is not None:
        return [
            f"  # {branch} has moved past the pin.",
            f"  #   {remote}/{branch} is at {tip} as of your last fetch; the lock wants {pin}.",
            "  # No checkout reaches the pin, so nothing you do to this working tree makes this",
            "  #   green -- the lock is what is out of date, not the checkout.",
            f"  git -C {path} fetch {remote}",
            "  # then advance the pin in siblings.lock.toml to whatever that fetch leaves",
            f"  #   {remote}/{branch} at, with a line in `why` saying what moved:",
            f'  #     commit = "{tip}"',
            f"  # If those commits are unwanted instead, reset {branch} to {pin} and force-push.",
        ]

    return [
        f"  # {pin} is not on {branch} at all ({remote}/{branch} is at {tip} as of your last",
        "  #   fetch), so no checkout reaches it. Either the branch was rewritten, or the pin",
        "  #   names a commit from somewhere else. Settle which, then correct",
        "  #   siblings.lock.toml. See SIBLINGS.md.",
    ]


def repair(name: str, spec: dict, problems: list[Problem]) -> list[str]:
    """The lines to print about a failed sibling: commands that work, or why none would.

    Driven by the problems `check` actually found rather than by the shas alone. Reasoning only
    about pin-versus-tip gets two states confidently wrong: a dirty tree sitting exactly on the
    pin draws a paragraph about the lock being out of date, and a pin that is simply an unpushed
    local commit gets called foreign, sending the reader hunting for a rewrite that never
    happened. In both the checkout is on the right commit and the advice was about the wrong
    thing entirely.

    `spec["path"]` is what goes into the printed commands, because that is the relative path the
    developer types; the resolved path is what this function interrogates.
    """
    lines = [f"  # {name}"]
    kinds = {problem.kind for problem in problems}
    checkout = (REPO_ROOT / spec["path"]).resolve()

    if "missing" in kinds:
        return lines + [f"  # no checkout at {checkout} -- clone it. See SIBLINGS.md."]

    # One checkout can be wrong in several ways at once, so these accumulate rather than
    # returning: a dirty tree does not stop the pin from also being stale.
    if "dirty" in kinds:
        lines += [
            f"  # Uncommitted changes in {spec['path']}. Commit them there if they are real work",
            "  #   -- nobody else can see them -- or stash them if they are not:",
            f"  git -C {spec['path']} stash",
        ]
    if "unpushed" in kinds:
        lines += [
            "  # This checkout's commits exist only on this machine, so the pin names something",
            "  #   nobody else can fetch. Push the branch:",
            f"  git -C {spec['path']} push {spec['remote']} {spec['branch']}",
        ]
    if kinds & {"commit", "branch"}:
        lines += pin_advice(spec, checkout)

    return lines


def main() -> int:
    if not LOCK.exists():
        print(f"{RED}missing {LOCK}{OFF}", file=sys.stderr)
        return 1

    siblings = tomllib.loads(LOCK.read_text())
    failed: dict[str, list[Problem]] = {}

    print(f"\n{BOLD}Sibling checkouts, against siblings.lock.toml{OFF}\n")
    for name, spec in siblings.items():
        problems = check(name, spec)
        if problems:
            failed[name] = problems
            print(f"  {RED}✗ {name}{OFF}")
            for problem in problems:
                print(f"      {problem.detail}")
        else:
            print(f"  {GREEN}✓ {name}{OFF}  {DIM}{spec['branch']} @ {spec['commit']}{OFF}")

    if not failed:
        print(f"\n{GREEN}All siblings match.{OFF}\n")
        return 0

    print(f"\n{YELLOW}To fix:{OFF}")
    for name, problems in failed.items():
        print()
        for line in repair(name, siblings[name], problems):
            print(line)
    # Changing a sibling checkout changes what uv resolves against, so the sync is part of the
    # repair rather than an afterthought -- and if it rewrites `uv.lock`, that change is real and
    # belongs in a commit. SIBLINGS.md explains why (#152).
    print("\n  uv sync\n")
    print(f"{DIM}Why each pin is what it is: see SIBLINGS.md{OFF}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
