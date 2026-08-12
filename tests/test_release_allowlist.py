"""What reaches the public release tree (#110's allowlist, built in #129).

This file does not ship -- `release_allowlist` is dev-only, so in the public repo the import
below would fail. `release_allowlist.RULES` classifies it out by name, and
`test_every_tracked_file_is_classified` is what keeps that decision honest.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import release_allowlist
from release_allowlist import Unclassified, classify, plan

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


# --------------------------------------------------------------------------------------
# The guard that makes the allowlist fail closed in both directions.
# --------------------------------------------------------------------------------------


def test_every_tracked_file_is_classified() -> None:
    """No tracked path may fall through the rules.

    This is the whole point of the design. When a branch adds a root-level file -- or a whole
    directory, as #116 does with the Sphinx source -- this test fails until someone says
    whether it ships. A plain allowlist would have shipped the release without it and said
    nothing.
    """
    unclassified = []
    for relpath in _tracked_files():
        try:
            classify(relpath)
        except Unclassified:
            unclassified.append(relpath)
    assert unclassified == []


def test_an_unknown_path_is_an_error_not_a_silent_exclusion() -> None:
    with pytest.raises(Unclassified):
        classify("NEW-ROOT-FILE.md")


def test_the_error_names_the_path_so_the_fix_is_obvious() -> None:
    with pytest.raises(Unclassified, match="NEW-ROOT-FILE.md"):
        classify("NEW-ROOT-FILE.md")


def test_every_rule_carries_a_reason() -> None:
    """A rule without a reason is a rule nobody can review at release time."""
    assert all(rule.why.strip() for rule in release_allowlist.RULES)


def test_no_rule_shadows_a_more_specific_one_below_it() -> None:
    """`classify` takes the first match, so a general rule placed above a specific one hides it.

    Asserted directly rather than trusted: reordering RULES by hand -- grouping all the
    exclusions together, say -- is exactly the tidy-up that would silently start shipping the
    decision records again, and `classify` would report no error at all.
    """
    shadowed = [
        (earlier.prefix, later.prefix)
        for i, earlier in enumerate(release_allowlist.RULES)
        for later in release_allowlist.RULES[i + 1 :]
        if earlier.prefix.endswith("/") and later.prefix.startswith(earlier.prefix)
    ]
    assert shadowed == []


# --------------------------------------------------------------------------------------
# What ships.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relpath",
    [
        "src/kapps_semantic_middleware/middleware.py",
        "src/kapps_semantic_middleware/CONTEXT.md",
        "src/kapps_semantic_middleware/shacl_interop/CONTEXT.md",
        "tests/test_release_checks.py",
        "demo/transferunits/CONTEXT.md",
        "examples/CONTEXT.md",
        "docker/docker-compose.yml",
        "docs/mechanics/01-instantiation-and-lifecycle.md",
        "docs/site/conf.py",
        "scripts/release_checks.py",
        "AGENTS.md",
        "CLAUDE.md",
        "CONTEXT-MAP.md",
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        ".env.example",
        ".python-version",
        ".gitignore",
    ],
)
def test_these_ship(relpath: str) -> None:
    assert classify(relpath).ships


# --------------------------------------------------------------------------------------
# What does not.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relpath",
    [
        "SIBLINGS.md",
        "siblings.lock.toml",
        "scripts/check_siblings.py",
        "scripts/check.sh",
        "scripts/prepare_release.py",
        "scripts/publish_release.py",
        "scripts/release_allowlist.py",
        "scripts/release_edits.py",
        "tests/test_release_allowlist.py",
        "tests/test_release_edits.py",
        ".github/workflows/checks.yml",
        ".vscode/settings.json",
        ".claude/settings.json",
        "docs/agents/issue-tracker.md",
        "docs/brownfield-gap-analysis.md",
    ],
)
def test_these_do_not_ship(relpath: str) -> None:
    assert not classify(relpath).ships


def test_both_record_directories_are_excluded_at_their_different_depths() -> None:
    """#129: there are two, 32 at one depth and 1 one level deeper.

    A rule written for the first silently misses the second, which is the failure mode the
    ticket calls out by name. The paths are assembled from the checker's own constant so this
    file carries no literal that check 5 would ban.
    """
    import release_checks

    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    shallow = f"src/kapps_semantic_middleware/{adr}0001-a.md"
    deep = f"src/kapps_semantic_middleware/shacl_interop/{adr}0001-b.md"
    leaked = f"examples/{adr}0001-self-contained-example-notebooks.md"

    assert not classify(shallow).ships
    assert not classify(deep).ships
    assert not classify(leaked).ships


def test_the_examples_leak_is_closed_against_the_real_tree() -> None:
    """The file really is tracked today, so this is a regression test and not a hypothetical."""
    import release_checks

    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    leaked = f"examples/{adr}0001-self-contained-example-notebooks.md"
    assert leaked in _tracked_files()
    assert leaked in plan(_tracked_files()).excluded


# --------------------------------------------------------------------------------------
# The plan over the real tree.
# --------------------------------------------------------------------------------------


def test_plan_splits_the_real_tree_without_losing_anything() -> None:
    tracked = _tracked_files()
    result = plan(tracked)
    assert sorted(result.ships + result.excluded) == sorted(tracked)
    assert set(result.ships).isdisjoint(result.excluded)


def test_no_record_directory_survives_the_plan() -> None:
    import release_checks

    ships = plan(_tracked_files()).ships
    for dead in release_checks.DEAD_REFERENCE_DIRS:
        assert not [p for p in ships if dead in p]


def test_nothing_named_by_check_three_survives_the_plan() -> None:
    """The allowlist and check 3 must agree, or the gate fires on every release."""
    import release_checks

    ships = plan(_tracked_files()).ships
    for fragment in release_checks.BANNED_PATH_FRAGMENTS:
        offenders = [p for p in ships if fragment in p]
        assert offenders == [], f"{fragment} survives in {offenders}"
