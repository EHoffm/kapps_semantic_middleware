"""Each of the five checks must fail the *run*, not merely return a value (#129).

`tests/test_release_checks.py` proves each check function spots its violation. That is not the
same claim. This file proves the **command** exits non-zero — the wiring between a check finding
something and the release actually stopping. A check that returns a violation nobody acts on is
the same as no check at all, and #129's acceptance asks for exactly this, probed one at a time.

`release_checks.main` is what `.github/workflows/hygiene.yml` runs in the public repo, so these
probes cover the CI backstop path directly.

This file ships. It imports only `release_checks`, which ships too, and it spells out no banned
literal — every planted violation is built from the checker's own constants.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import release_checks
from release_checks import main

ORIGIN = "https://github.com/circularfactory/kapps_semantic_middleware.git"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def clean_release(tmp_path: Path) -> Path:
    """A tree that passes all five checks: one clean commit, only the release origin."""
    root = tmp_path / "release"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# a release\n")
    (root / "AGENTS.md").write_text("See the mechanics pages.\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release: v0.1.0")
    _git(root, "remote", "add", "origin", ORIGIN)
    return root


def test_a_clean_tree_exits_zero(clean_release: Path) -> None:
    """The baseline. Without this, a probe passing proves nothing."""
    assert main([str(clean_release), "--origin", ORIGIN]) == 0


# --------------------------------------------------------------------------------------
# One probe per check. Each plants exactly one violation into an otherwise clean release.
# --------------------------------------------------------------------------------------


def test_probe_one_a_second_remote_fails_the_run(clean_release: Path) -> None:
    _git(
        clean_release,
        "remote",
        "add",
        "dev",
        "https://github.com/EHoffm/kapps_semantic_middleware.git",
    )
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_one_a_diverted_push_url_fails_the_run(clean_release: Path) -> None:
    """The subtle half of check 1: fetch stays right, push goes to the dev repo."""
    _git(
        clean_release,
        "remote",
        "set-url",
        "--push",
        "origin",
        "https://github.com/EHoffm/kapps_semantic_middleware.git",
    )
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_two_an_agent_trailer_fails_the_run(clean_release: Path) -> None:
    (clean_release / "extra.md").write_text("x\n")
    _git(clean_release, "add", "-A")
    _git(
        clean_release,
        "commit",
        "-q",
        "-m",
        "fix: something\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
    )
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_three_a_dev_only_path_fails_the_run(clean_release: Path) -> None:
    agents_dir = clean_release / "docs" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "issue-tracker.md").write_text("dev-side configuration\n")
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_four_the_private_host_fails_the_run(clean_release: Path) -> None:
    (clean_release / "notes.md").write_text(f"clone from https://{release_checks.PRIVATE_HOST}/x\n")
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_five_a_dead_record_pointer_fails_the_run(clean_release: Path) -> None:
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (clean_release / "CONTEXT.md").write_text(f"See `src/pkg/{adr}0004-endpoint.md`.\n")
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


def test_probe_five_a_bare_directory_mention_fails_the_run(clean_release: Path) -> None:
    """Settled with Etienne: a public README naming a folder that is not there also fails."""
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (clean_release / "README.md").write_text(f"| `{adr}` | Root records. |\n")
    assert main([str(clean_release), "--origin", ORIGIN]) == 1


# --------------------------------------------------------------------------------------
# The CI backstop runs without --origin, so checks 1 and 2 are out of scope there.
# --------------------------------------------------------------------------------------


def test_without_an_origin_the_tree_checks_still_run(clean_release: Path) -> None:
    (clean_release / "SIBLINGS.md").write_text("x\n")
    assert main([str(clean_release)]) == 1


def test_without_an_origin_a_bad_remote_is_not_examined(clean_release: Path) -> None:
    """`hygiene.yml` passes no origin: a CI checkout's remote says nothing about the release."""
    _git(clean_release, "remote", "add", "dev", "https://example.invalid/x.git")
    assert main([str(clean_release)]) == 0


def test_the_run_reports_every_violation_not_only_the_first(
    clean_release: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One fix per run would make a five-violation tree take five runs to clear."""
    (clean_release / "SIBLINGS.md").write_text("x\n")
    (clean_release / "leak.md").write_text(release_checks.PRIVATE_HOST + "\n")
    (clean_release / "dead.md").write_text(release_checks.DEAD_REFERENCE_DIRS[1] + "\n")

    assert main([str(clean_release)]) == 1

    out = capsys.readouterr().out
    assert "SIBLINGS.md" in out
    assert "leak.md" in out
    assert "dead.md" in out
