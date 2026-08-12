"""`--dry-run` must change nothing, and the state file is what "nothing" is about (#158).

`prepare_release.py` and `publish_release.py` are two halves of one mechanism with a human
review in between, and `.release-state.json` is the entire join: the second script reads the
reviewed tip out of it and refuses a branch that has moved since. #110 calls that gate
"enforced, not ceremonial", and it is enforced only for as long as the file says what somebody
actually reviewed.

So a dry run that writes the file destroys the gate -- and does it under the one command whose
whole promise is to change nothing, which is where nobody looks. The fork hit this during a
real release (#118) and fixed it there; #158 is the fix coming back.

This file does not ship: it imports `prepare_release`, which is dev-only.
"""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

import prepare_release
import release_plumbing

REPO_ROOT = Path(__file__).resolve().parents[1]

SENTINEL = json.dumps(
    {
        "version": "9.9.9",
        "branch": "prepare-release",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "prepared_at": "2026-01-01T00:00:00+00:00",
        "cross_checked": True,
    },
    indent=2,
).encode("utf-8") + b"\n"
"""A plausible record of a real, reviewed release. Byte-for-byte is the assertion."""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def dev_repo(tmp_path: Path) -> Path:
    """A throwaway repo holding **this repository's real tree** at one commit on `main`.

    Real content rather than a hand-built minimum, and not for convenience: `release_allowlist`
    stops the run on any tracked path it does not recognise, and every entry in
    `release_edits.REWRITES` is an exact match against real prose that must hit exactly once. A
    fixture inventing its own files would fail at the allowlist, and one inventing its own prose
    would fail at the edits -- in both cases before reaching the line under test, and the test
    would then pass for the wrong reason.

    `git archive` is used rather than `git clone` so the copy carries no remotes: a dry run must
    not push, and a fixture that could reach a real remote is a fixture that eventually does.
    """
    root = tmp_path / "dev"
    root.mkdir()

    archive = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "HEAD"],
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r|") as tar:
        tar.extractall(root, filter="data")

    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.org")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "the tree under test")
    return root


@pytest.fixture(autouse=True)
def _prepare_from_the_stand_in_repo(monkeypatch: pytest.MonkeyPatch, dev_repo: Path) -> None:
    """Point the script at the throwaway repo instead of this checkout.

    Both modules are patched. `prepare_release` imported `REPO_ROOT` by value, so rebinding it
    on `release_plumbing` alone would leave the driver reading the developer's own checkout --
    and a test that force-pushed a branch there would be a memorable way to find that out.
    """
    monkeypatch.setattr(release_plumbing, "REPO_ROOT", dev_repo)
    monkeypatch.setattr(prepare_release, "REPO_ROOT", dev_repo)


def _version(repo: Path) -> str:
    """The version the manifest declares, so this file does not go stale at the next release."""
    for line in (repo / "pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            return line.split('"')[1]
    raise AssertionError("no version in pyproject.toml")


def test_a_dry_run_leaves_an_existing_state_file_byte_for_byte_untouched(dev_repo: Path) -> None:
    """The state file is the review gate, and a dry run must not be able to move it.

    Before the fix, every dry run overwrote it -- recording the string
    "(not computed in dry-run)" where the reviewed SHA had been. `publish_release.py` then had
    no way to tell that the tree it was about to publish was not the tree anybody approved.
    """
    state_path = dev_repo / ".release-state.json"
    state_path.write_bytes(SENTINEL)

    code = prepare_release.main(
        ["--version", _version(dev_repo), "--dry-run", "--skip-cross-check"]
    )

    assert code == 0
    assert state_path.read_bytes() == SENTINEL


def test_a_dry_run_writes_no_state_file_where_there_was_none(dev_repo: Path) -> None:
    """The other half: it must not create one either.

    A file that appears out of a dry run is a file `publish_release.py` will read, and it would
    name a tip nobody cut.
    """
    state_path = dev_repo / ".release-state.json"
    assert not state_path.exists()

    code = prepare_release.main(
        ["--version", _version(dev_repo), "--dry-run", "--skip-cross-check"]
    )

    assert code == 0
    assert not state_path.exists()


def test_a_dry_run_creates_no_release_branch(dev_repo: Path) -> None:
    """"Would create prepare-release" has to stay a sentence rather than an action."""
    code = prepare_release.main(
        ["--version", _version(dev_repo), "--dry-run", "--skip-cross-check"]
    )

    assert code == 0
    branches = _git(dev_repo, "branch", "--format=%(refname:short)").split()
    assert branches == ["main"]


def test_a_real_run_records_the_tip_and_the_cross_check(dev_repo: Path) -> None:
    """The state file must carry a usable SHA and say whether the wheel was ever built.

    `cross_checked` is what lets `publish_release.py` tell a gated release from an ungated one.
    Without it, `--skip-cross-check` leaves no trace anywhere and the second script cannot warn
    about something the first one skipped.
    """
    _git(dev_repo, "remote", "add", "origin", str(dev_repo))

    code = prepare_release.main(["--version", _version(dev_repo), "--skip-cross-check"])

    assert code == 0
    state = json.loads((dev_repo / ".release-state.json").read_text())
    assert state["branch"] == "prepare-release"
    assert state["cross_checked"] is False
    assert state["sha"] == _git(dev_repo, "rev-parse", "prepare-release").strip()
    assert "not computed" not in state["sha"]


def test_a_dirty_tracked_file_stops_the_run(dev_repo: Path) -> None:
    """The tree being reviewed must be the tree that would ship.

    A modified tracked file means the diff a human reads is not the diff that was staged, and
    reviewing under that illusion is what this preflight exists to prevent.
    """
    (dev_repo / "README.md").write_text("locally edited\n")

    code = prepare_release.main(
        ["--version", _version(dev_repo), "--dry-run", "--skip-cross-check"]
    )

    assert code == 1
