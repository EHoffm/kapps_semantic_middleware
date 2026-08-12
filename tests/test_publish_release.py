"""The irreversible half of the release mechanism (#129).

`prepare_release.py` can be re-run all day; `publish_release.py` pushes to a public repository
and fires a PyPI workflow, and there is no second chance at either. #129's acceptance asks for
one probe by name -- *"`publish_release.py` refuses to run against a moved tip. Probed: move the
tip, confirm it exits non-zero"* -- and that guard is what makes the human review a gate rather
than a ceremony.

Everything here runs offline. The "public repo" is a bare repository in `tmp_path`, which `git
clone`, `git ls-remote` and `git push` all treat exactly like a remote, so the end-to-end path
is exercised for real rather than mocked: a first release into an empty repo, a second on top
of it, and the linear line between them.

This file does not ship. It imports `publish_release`, which is dev-only; `release_allowlist`
classifies it out by name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import publish_release
import release_checks
from conftest import git_in as _git

VERSION = "0.1.0"


@pytest.fixture
def dev_repo(tmp_path: Path) -> Path:
    """A stand-in dev repo whose `prepare-release` branch holds a clean, shippable tree."""
    root = tmp_path / "dev"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# a release\n")
    (root / "AGENTS.md").write_text("See the mechanics pages.\n")
    (root / "src").mkdir()
    (root / "src" / "thing.py").write_text("VALUE = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release: v0.1.0")
    _git(root, "branch", "prepare-release")
    return root


@pytest.fixture
def public_repo(tmp_path: Path) -> str:
    """An empty bare repository standing in for the circularfactory remote."""
    bare = tmp_path / "public.git"
    bare.mkdir()
    _git(bare, "init", "-q", "--bare", "-b", "main")
    return str(bare)


@pytest.fixture
def state_file(dev_repo: Path) -> Path:
    """The handover `prepare_release.py` writes: version, branch, and the tip it reviewed."""
    sha = _git(dev_repo, "rev-parse", "prepare-release").strip()
    path = dev_repo / ".release-state.json"
    path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "branch": "prepare-release",
                "sha": sha,
                "prepared_at": "2026-08-12T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n"
    )
    return path


@pytest.fixture(autouse=True)
def _publish_from_the_stand_in_repo(
    monkeypatch: pytest.MonkeyPatch, dev_repo: Path
) -> None:
    """Point the script at the throwaway dev repo instead of this checkout.

    `REPO_ROOT` is a module constant read at call time, which is the only reason the script is
    testable at all without a live repository under `circularfactory`.
    """
    monkeypatch.setattr(publish_release, "REPO_ROOT", dev_repo)


def _publish(repo: str, *extra: str) -> int:
    return publish_release.main(["--repo", repo, "--yes", *extra])


def _temp_clones() -> list[Path]:
    """Every staging clone the script has left behind, across all runs on this machine."""
    import tempfile

    return list(Path(tempfile.gettempdir()).glob("publish-release-*"))


# --------------------------------------------------------------------------------------
# The gate #129 names: a tip that moved after review.
# --------------------------------------------------------------------------------------


def test_a_moved_tip_stops_the_release(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """The probe #129's acceptance asks for by name.

    Amending the branch after review means the tree a human approved is not the tree about to
    become public. Without this the two-script split buys nothing: the review would describe
    one commit and the push would publish another.
    """
    (dev_repo / "sneaked-in.md").write_text("added after the review\n")
    _git(dev_repo, "checkout", "-q", "prepare-release")
    _git(dev_repo, "add", "-A")
    _git(dev_repo, "commit", "-q", "-m", "release: v0.1.0 (amended)")

    assert _publish(public_repo) == 1
    assert _git(Path(public_repo), "rev-list", "--all", "--count").strip() == "0"


def test_a_deleted_branch_stops_the_release(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    _git(dev_repo, "branch", "-q", "-D", "prepare-release")
    assert _publish(public_repo) == 1


def test_a_missing_state_file_stops_the_release(dev_repo: Path, public_repo: str) -> None:
    """No state file means no review happened. There is nothing to publish."""
    assert _publish(public_repo) == 1


def test_a_truncated_state_file_stops_the_release(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    state_file.write_text(json.dumps({"version": VERSION}) + "\n")
    assert _publish(public_repo) == 1


def test_an_existing_tag_stops_the_release(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """A release is published once. The version is the identity, so it cannot be reused."""
    _git(dev_repo, "tag", f"v{VERSION}")
    assert _publish(public_repo) == 1


# --------------------------------------------------------------------------------------
# The five checks, wired to the irreversible act.
# --------------------------------------------------------------------------------------


def test_a_dead_record_pointer_stops_the_release_before_any_push(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """`release_checks` finding something must stop *this* script, not merely return a list.

    `tests/test_release_cli.py` proves the checks fail the checker's own command. This proves
    the wiring on the path where failing to stop is unrecoverable.
    """
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    _git(dev_repo, "checkout", "-q", "prepare-release")
    (dev_repo / "CONTEXT.md").write_text(f"See `src/pkg/{adr}0004-endpoint.md`.\n")
    _git(dev_repo, "add", "-A")
    _git(dev_repo, "commit", "-q", "-m", "release: v0.1.0")
    state_file.write_text(
        json.dumps(
            {
                "version": VERSION,
                "branch": "prepare-release",
                "sha": _git(dev_repo, "rev-parse", "prepare-release").strip(),
                "prepared_at": "2026-08-12T00:00:00+00:00",
            }
        )
        + "\n"
    )

    assert _publish(public_repo) == 1
    assert _git(Path(public_repo), "rev-list", "--all", "--count").strip() == "0"


def test_an_agent_trailer_already_in_the_public_history_stops_the_release(
    dev_repo: Path, public_repo: str, state_file: Path, tmp_path: Path
) -> None:
    """Check 2 guards the line being extended, not the branch being read.

    The clone's history is the *public* one, so this is the case check 2 can actually catch
    here: a commit made straight into the public repo, by hand or through the web UI. A
    release must not be stacked on top of it and make it permanent.
    """
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", public_repo, str(seed))
    (seed / "README.md").write_text("# a release\n")
    _git(seed, "add", "-A")
    _git(
        seed,
        "commit",
        "-q",
        "-m",
        "fix: a typo\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
    )
    _git(seed, "push", "-q", "origin", "HEAD:main")

    assert _publish(public_repo) == 1

    bare = Path(public_repo)
    assert _git(bare, "rev-list", "--count", "main").strip() == "1"
    assert _git(bare, "tag", "-l").split() == []


def test_the_dev_history_never_crosses_over(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """Only the tree is exported, never the log -- which is why one release is one commit.

    Every trailer, branch name and review comment in the dev repo stops at the boundary by
    construction rather than by filtering, and `git archive` is what makes that true.
    """
    _git(dev_repo, "checkout", "-q", "prepare-release")
    _git(
        dev_repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "wip: fiddling\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
    )
    state_file.write_text(
        json.dumps(
            {
                "version": VERSION,
                "branch": "prepare-release",
                "sha": _git(dev_repo, "rev-parse", "prepare-release").strip(),
                "prepared_at": "2026-08-12T00:00:00+00:00",
            }
        )
        + "\n"
    )

    assert _publish(public_repo) == 0

    public_log = _git(Path(public_repo), "log", "--format=%B", "main")
    assert "wip: fiddling" not in public_log
    assert "Co-Authored-By" not in public_log


# --------------------------------------------------------------------------------------
# The end-to-end shape, against a bare repository that behaves like the real remote.
# --------------------------------------------------------------------------------------


def test_a_first_release_lands_as_one_commit_and_one_tag(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """#129's destination: one commit per release, tagged, on a repo that started empty."""
    assert _publish(public_repo) == 0

    bare = Path(public_repo)
    assert _git(bare, "rev-list", "--count", "main").strip() == "1"
    assert _git(bare, "log", "-1", "--format=%s", "main").strip() == f"release: v{VERSION}"
    assert _git(bare, "tag", "-l").split() == [f"v{VERSION}"]

    shipped = _git(bare, "ls-tree", "-r", "--name-only", "main").split()
    assert set(shipped) == {"README.md", "AGENTS.md", "src/thing.py"}


def test_the_second_release_continues_the_line_rather_than_starting_a_new_one(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """`git diff v0.1.0..v0.2.0` has to work for a stranger, so the parent is the last release."""
    assert _publish(public_repo) == 0
    first = _git(Path(public_repo), "rev-parse", "main").strip()

    _git(dev_repo, "checkout", "-q", "prepare-release")
    (dev_repo / "src" / "thing.py").write_text("VALUE = 2\n")
    _git(dev_repo, "add", "-A")
    _git(dev_repo, "commit", "-q", "-m", "release: v0.2.0")
    state_file.write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "branch": "prepare-release",
                "sha": _git(dev_repo, "rev-parse", "prepare-release").strip(),
                "prepared_at": "2026-08-12T00:00:00+00:00",
            }
        )
        + "\n"
    )

    assert _publish(public_repo) == 0

    bare = Path(public_repo)
    assert _git(bare, "rev-list", "--count", "main").strip() == "2"
    assert _git(bare, "rev-parse", "main^").strip() == first
    assert sorted(_git(bare, "tag", "-l").split()) == ["v0.1.0", "v0.2.0"]


def test_a_file_dropped_between_releases_leaves_the_public_tree(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """The clone is emptied before the tree is copied in, so a release is a mirror not a merge."""
    assert _publish(public_repo) == 0

    _git(dev_repo, "checkout", "-q", "prepare-release")
    _git(dev_repo, "rm", "-q", "AGENTS.md")
    _git(dev_repo, "commit", "-q", "-m", "release: v0.2.0")
    state_file.write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "branch": "prepare-release",
                "sha": _git(dev_repo, "rev-parse", "prepare-release").strip(),
                "prepared_at": "2026-08-12T00:00:00+00:00",
            }
        )
        + "\n"
    )

    assert _publish(public_repo) == 0
    assert "AGENTS.md" not in _git(Path(public_repo), "ls-tree", "-r", "--name-only", "main")


# --------------------------------------------------------------------------------------
# What the run leaves behind.
# --------------------------------------------------------------------------------------


def test_a_published_release_retires_its_state_file(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """The state file describes a release that has happened; leaving it invites a second run.

    The moved-tip guard would wave that second run straight through -- the tip has not moved --
    and it would fail much later, on the tag preflight. This deletion was written below the
    `finally` block, where no return path can reach it, so it never once ran.
    """
    assert _publish(public_repo) == 0
    assert not state_file.exists()


def test_a_dry_run_keeps_the_state_file_and_touches_nothing_public(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    assert _publish(public_repo, "--dry-run") == 0
    assert state_file.exists()
    assert _git(Path(public_repo), "rev-list", "--all", "--count").strip() == "0"


def test_a_successful_publish_cleans_up_its_staging_clone(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    """Success is not a state anyone inspects.

    The first version reported every successful publish as a failure -- it preserved the clone
    and printed "Clone preserved for inspection", because by then a commit had been made and
    that was the only thing the cleanup looked at.
    """
    before = set(_temp_clones())
    assert _publish(public_repo) == 0
    assert set(_temp_clones()) == before


def test_a_run_that_stops_before_committing_cleans_up_too(
    dev_repo: Path, public_repo: str, state_file: Path
) -> None:
    before = set(_temp_clones())
    _git(dev_repo, "checkout", "-q", "prepare-release")
    (dev_repo / "leak.md").write_text(f"clone from https://{release_checks.PRIVATE_HOST}/x\n")
    _git(dev_repo, "add", "-A")
    _git(dev_repo, "commit", "-q", "-m", "release: v0.1.0")
    state_file.write_text(
        json.dumps(
            {
                "version": VERSION,
                "branch": "prepare-release",
                "sha": _git(dev_repo, "rev-parse", "prepare-release").strip(),
                "prepared_at": "2026-08-12T00:00:00+00:00",
            }
        )
        + "\n"
    )

    assert _publish(public_repo) == 1
    assert set(_temp_clones()) == before
