"""The repair advice `check_siblings.py` prints must be advice that can actually work (#152).

The check itself is not the interesting part -- it compares three strings. What cost real time
during #146 is what it prints when it fails: an unconditional

    git -C ../aas_middleware_inf fetch origin
    git -C ../aas_middleware_inf checkout dev_semantic_middleware

which lands on the *branch tip*. When the tip has moved past the pin -- which is exactly the state
#152 was filed about -- following those two lines leaves the check red and now reports
``at 8dc7291, want 999ef52``. The tool tells you to do something that cannot satisfy it, and the
next person's reasonable conclusion is that the check is broken and can be ignored.

So these tests are about the *advice*, not the verdict. Each builds a throwaway sibling repository
in ``tmp_path`` and asks what `check_siblings` would tell a developer to do about it.

This file does not ship: `check_siblings.py` is dev-only and `release_allowlist` classifies it out.
Both it and this file are deleted by #120, which removes the editable path sources that make a
sibling lock necessary at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_siblings
from conftest import git_in as _git

BRANCH = "dev_semantic_middleware"


def _commit(repo: Path, message: str) -> str:
    """Add one file's worth of change and return the resulting short sha."""
    (repo / "file.txt").write_text(message)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "--short", "HEAD").strip()


@pytest.fixture
def sibling(tmp_path: Path) -> Path:
    """A sibling checkout on `BRANCH` with one commit, pushed to a bare origin.

    The origin exists so the branch has an upstream: without one the check reports "nobody else
    can obtain this commit", which is a different failure from the one under test.
    """
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(bare, "init", "-q", "--bare", "-b", BRANCH)

    repo = tmp_path / "sibling"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", BRANCH)
    _commit(repo, "first")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", BRANCH)
    return repo


def _spec(repo: Path, commit: str) -> dict:
    return {
        "path": str(repo),
        "branch": BRANCH,
        "commit": commit,
        "remote": "origin",
        "why": "under test",
    }


def _advice(repo: Path, commit: str) -> str:
    """What the tool would print about a sibling pinned at `commit`, as one string.

    Goes through `check` rather than calling `repair` with a hand-built problem list, because
    the pairing of the two is the thing under test: advice that does not answer the problem
    that actually fired is the defect this file exists to catch.
    """
    spec = _spec(repo, commit)
    return "\n".join(check_siblings.repair("sibling", spec, check_siblings.check("sibling", spec)))


def test_pin_at_branch_tip_advises_a_checkout(sibling: Path) -> None:
    """The ordinary stale checkout: the pin is the tip, so checking the branch out reaches it."""
    tip = _git(sibling, "rev-parse", "--short", "HEAD").strip()
    _git(sibling, "checkout", "-q", "--detach", "HEAD")

    advice = _advice(sibling, tip)

    assert f"checkout {BRANCH}" in advice
    assert "fetch origin" in advice


def test_branch_ahead_of_pin_does_not_advise_a_checkout(sibling: Path) -> None:
    """#152's trap. The tip has moved past the pin, so a checkout lands on the wrong commit.

    The advice must not offer that checkout as the fix, and must name the lock file, because
    advancing the pin is the only thing that makes this sibling green.
    """
    pin = _git(sibling, "rev-parse", "--short", "HEAD").strip()
    tip = _commit(sibling, "second")
    _git(sibling, "push", "-q", "origin", BRANCH)

    advice = _advice(sibling, pin)

    assert f"checkout {BRANCH}" not in advice
    assert pin in advice and tip in advice
    assert "siblings.lock.toml" in advice


def test_pin_not_on_the_branch_at_all_says_so(sibling: Path, tmp_path: Path) -> None:
    """A pin that no amount of checking out can reach -- a rewritten or foreign commit.

    Naming a checkout here would be the same lie as the case above, one step further from home.
    """
    _git(sibling, "checkout", "-q", "-b", "elsewhere")
    orphan = _commit(sibling, "orphan")
    _git(sibling, "checkout", "-q", BRANCH)

    advice = _advice(sibling, orphan)

    assert f"checkout {BRANCH}" not in advice
    assert orphan in advice
    assert BRANCH in advice


def test_a_dirty_tree_is_told_to_commit_or_stash(sibling: Path) -> None:
    """The advice has to answer the problem that actually fired, not the one it can compute.

    HEAD sits exactly on the pin here, so the pin is not the complaint -- the uncommitted change
    is. Reasoning only about pin-versus-tip produces a confident sentence about the lock being
    out of date while the developer's real problem goes unmentioned.
    """
    pin = _git(sibling, "rev-parse", "--short", "HEAD").strip()
    _commit(sibling, "second")
    _git(sibling, "push", "-q", "origin", BRANCH)
    _git(sibling, "reset", "-q", "--hard", pin)
    (sibling / "file.txt").write_text("edited, not committed")

    advice = _advice(sibling, pin)

    assert "stash" in advice or "commit or" in advice
    assert "the lock is what is out of date" not in advice


def test_an_unpushed_pin_is_told_to_push(sibling: Path) -> None:
    """A pin nobody else can fetch. The answer is `git push`, and it is not about the branch.

    The checkout is on the right branch at the right commit; what is wrong is that the commit
    exists on one machine only. Advice that calls the pin foreign sends the reader hunting for
    a rewrite that never happened.
    """
    pin = _commit(sibling, "second")

    advice = _advice(sibling, pin)

    assert "push" in advice
    assert "rewritten" not in advice


def test_missing_checkout_points_at_the_setup_document(tmp_path: Path) -> None:
    """Nothing to fetch in a directory that is not a checkout; cloning is the whole answer."""
    advice = _advice(tmp_path / "absent", "abc1234")

    assert "fetch origin" not in advice
    assert "SIBLINGS.md" in advice
