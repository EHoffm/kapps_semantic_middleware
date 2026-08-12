"""What the built wheel must and must not contain (#129).

This file does not ship: it imports `prepare_release`, which is dev-only.

It exists because the first version of `wheel_problems` was a **no-op**. It derived a prefix by
dropping the first path segment of the record directory, leaving `"adr/"`, and tested
`entry.startswith("adr/")` -- which no wheel entry can ever satisfy, since every entry begins
with the package name. The dry run printed "content checks passed" and had checked nothing. The
wheel really was clean, but only because the allowlist had already pruned the records, so the
mistake was invisible from the outcome. Copilot caught it on PR #144.

Every test below therefore asserts on a *dirty* input as well as a clean one. A guard that
cannot fail is not a guard.
"""

from __future__ import annotations

import pytest

import release_checks
from prepare_release import PACKAGE, wheel_problems

ADR = release_checks.DEAD_REFERENCE_DIRS[0]
PRD = release_checks.DEAD_REFERENCE_DIRS[1]

CLEAN = [
    f"{PACKAGE}/__init__.py",
    f"{PACKAGE}/middleware.py",
    f"{PACKAGE}/AGENTS.md",
    f"{PACKAGE}/CONTEXT-MAP.md",
    f"{PACKAGE}/CONTEXT.md",
    f"{PACKAGE}/docs/mechanics/01-instantiation-and-lifecycle.md",
    f"{PACKAGE}/docs/mechanics/07-writing-to-the-graph-and-to-devices.md",
    f"{PACKAGE}/demonstrations/launcher.py",
    "kapps_semantic_middleware-0.1.0.dist-info/METADATA",
]


def test_a_clean_wheel_has_no_problems() -> None:
    assert wheel_problems(CLEAN) == []


# --------------------------------------------------------------------------------------
# The records must be gone -- at BOTH depths.
# --------------------------------------------------------------------------------------


def test_a_record_at_the_shallow_depth_is_caught() -> None:
    entries = [*CLEAN, f"{PACKAGE}/{ADR}0001-a-decision.md"]
    problems = wheel_problems(entries)
    assert len(problems) == 1
    assert problems[0].startswith("forbidden:")


def test_a_record_at_the_deeper_depth_is_caught() -> None:
    """#129 names this shape as the trap: 32 records at one depth and 1 one level deeper.

    This is the case a rule written for the first directory silently misses.
    """
    entries = [*CLEAN, f"{PACKAGE}/shacl_interop/{ADR}0001-shacl.md"]
    problems = wheel_problems(entries)
    assert len(problems) == 1
    assert "shacl_interop" in problems[0]


def test_both_depths_are_caught_together() -> None:
    entries = [
        *CLEAN,
        f"{PACKAGE}/{ADR}0001-a.md",
        f"{PACKAGE}/shacl_interop/{ADR}0001-b.md",
    ]
    assert len(wheel_problems(entries)) == 2


def test_a_requirements_document_is_caught_too() -> None:
    entries = [*CLEAN, f"{PACKAGE}/{PRD}some-requirement.md"]
    assert len(wheel_problems(entries)) == 1


def test_the_real_shape_of_todays_wheel_would_be_caught() -> None:
    """Before the allowlist prunes them, the wheel ships 33 records: 32 shallow and 1 deep.

    Measured against a real `uv build` on 2026-08-11. If `wheel_problems` cannot fail on this
    input, it cannot do its job.
    """
    entries = [
        *CLEAN,
        *[f"{PACKAGE}/{ADR}{n:04d}-record.md" for n in range(1, 33)],
        f"{PACKAGE}/shacl_interop/{ADR}0001-shacl.md",
    ]
    assert len(wheel_problems(entries)) == 33


# --------------------------------------------------------------------------------------
# The replacements must be present -- the positive twin.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("dropped", ["AGENTS.md", "CONTEXT-MAP.md"])
def test_a_missing_doc_is_caught(dropped: str) -> None:
    entries = [e for e in CLEAN if e != f"{PACKAGE}/{dropped}"]
    problems = wheel_problems(entries)
    assert problems == [f"missing: {PACKAGE}/{dropped}"]


def test_missing_mechanics_pages_are_caught() -> None:
    entries = [e for e in CLEAN if "/docs/mechanics/" not in e]
    assert wheel_problems(entries) == ["missing: every mechanics page"]


def test_dropping_the_records_and_their_replacements_together_still_fails() -> None:
    """The worse outcome, and the reason both halves are asserted.

    A wheel with neither the records nor the pages replacing them leaves a consuming agent
    reading `CONTEXT.md`'s citations with nothing that answers them. Checking only that the
    records are gone would call that a pass.
    """
    entries = [
        e
        for e in CLEAN
        if "/docs/mechanics/" not in e and not e.endswith(("AGENTS.md", "CONTEXT-MAP.md"))
    ]
    assert len(wheel_problems(entries)) == 3


def test_the_package_name_is_not_hardcoded_into_the_matching() -> None:
    """A prefix test against the package name is what made the first version a no-op."""
    entries = [f"other_pkg/{ADR}0001-a.md", "other_pkg/AGENTS.md", "other_pkg/CONTEXT-MAP.md"]
    entries.append("other_pkg/docs/mechanics/01-x.md")
    assert wheel_problems(entries, package="other_pkg") == [
        f"forbidden: other_pkg/{ADR}0001-a.md"
    ]
