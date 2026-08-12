"""The release-time edits (#129).

This file does not ship: it imports `release_edits`, which is dev-only, and the rewrite table it
asserts against quotes the record paths check 5 bans. `release_allowlist.RULES` classifies it out
by name.

The load-bearing test here is `test_every_declared_edit_matches_the_real_tree_exactly_once`. The
rewrites are exact string matches, so a reworded glossary breaks them -- and this is where that
break is meant to surface, on a normal working day, rather than during a release.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import release_checks
import release_edits
from release_edits import (
    REWRITES,
    SECTION_DROPS,
    RewriteError,
    SectionDrop,
    apply_all,
    apply_rewrite,
    apply_section_drop,
    edit_pyproject,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of every file the edits touch, at its real path, with its real content."""
    root = tmp_path / "tree"
    for relpath in {r.path for r in REWRITES} | {d.path for d in SECTION_DROPS}:
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relpath, target)
    return root


# --------------------------------------------------------------------------------------
# The guard on brittleness: every declared edit must still fit the real tree.
# --------------------------------------------------------------------------------------


def test_every_declared_edit_matches_the_real_tree_exactly_once() -> None:
    misses = []
    for rewrite in REWRITES:
        source = (REPO_ROOT / rewrite.path).read_text()
        hits = source.count(rewrite.old)
        if hits != 1:
            misses.append(f"{rewrite.path}: {hits} matches")
    assert misses == []


def test_every_declared_section_drop_finds_its_heading() -> None:
    for drop in SECTION_DROPS:
        assert drop.heading in (REPO_ROOT / drop.path).read_text()


def test_every_edit_carries_a_reason() -> None:
    for edit in (*REWRITES, *SECTION_DROPS):
        assert edit.why.strip()


def test_a_reworded_file_fails_loudly_rather_than_silently_skipping() -> None:
    rewrite = REWRITES[0]
    with pytest.raises(RewriteError, match="expected exactly 1 match, found 0"):
        apply_rewrite("some file that was reworded", rewrite)


def test_a_missing_heading_fails_loudly() -> None:
    drop = SECTION_DROPS[0]
    with pytest.raises(RewriteError, match="not found"):
        apply_section_drop("# A document without that section\n", drop)


# --------------------------------------------------------------------------------------
# What the edits achieve: check 5 passes over the edited tree.
# --------------------------------------------------------------------------------------


def test_the_edited_tree_has_no_record_pointers_left(tree: Path) -> None:
    """The acceptance criterion, asserted against the real files rather than a fixture."""
    before = release_checks.check_references(tree)
    assert before, "the fixture must start dirty, or this test proves nothing"

    apply_all(tree)

    assert release_checks.check_references(tree) == []


def test_apply_all_reports_every_file_it_touched(tree: Path) -> None:
    changed = apply_all(tree)
    assert set(changed) == {r.path for r in REWRITES} | {d.path for d in SECTION_DROPS}


def test_apply_all_is_not_idempotent_and_says_so(tree: Path) -> None:
    """Running twice must fail rather than quietly no-op: a second run means a lost first run."""
    apply_all(tree)
    with pytest.raises(RewriteError):
        apply_all(tree)


def test_bare_citations_survive_the_edits(tree: Path) -> None:
    """#130 measured that the citation form is read as provenance, so it stays."""
    apply_all(tree)
    glossary = (tree / "src/kapps_semantic_middleware/CONTEXT.md").read_text()
    assert "ADR 00" in glossary


def test_the_context_map_keeps_its_five_contexts(tree: Path) -> None:
    """Module Requirements is reworded, not deleted -- four other files say 'five contexts'."""
    apply_all(tree)
    context_map = (tree / "CONTEXT-MAP.md").read_text()
    assert "Module Requirements" in context_map
    assert context_map.count("\n- ") >= 5


def test_the_dropped_section_takes_its_whole_body_with_it(tree: Path) -> None:
    apply_all(tree)
    context_map = (tree / "CONTEXT-MAP.md").read_text()
    assert "Where the ADRs live" not in context_map
    assert "Root records — above every context" not in context_map
    assert "Where the decisions are written down" in context_map


def test_the_source_docstring_is_still_valid_python(tree: Path) -> None:
    """The one edit that touches code, not prose."""
    apply_all(tree)
    edited = tree / "src/kapps_semantic_middleware/shacl_interop/shape_from_typehints.py"
    compile(edited.read_text(), str(edited), "exec")


def test_the_released_readme_describes_the_end_state_not_the_dev_world(tree: Path) -> None:
    """The README must wind forward to what is true at release, not what is true today.

    By release every dependency resolves from PyPI. A README still describing editable path
    checkouts on unmerged branches -- and telling a stranger they need private KIT GitLab
    access -- would be false on the day it shipped, and correcting it would cost a whole
    second release. No hygiene check catches this: check 3 bans the *files*, and nothing bans
    a shipped file from talking about them.
    """
    apply_all(tree)
    readme = (tree / "README.md").read_text()

    for dev_only in ("SIBLINGS.md", "check_siblings.py", "editable path checkout", "GitLab"):
        assert dev_only not in readme, f"released README still mentions {dev_only!r}"

    assert "pip install kapps-semantic-middleware" in readme


def test_no_shipped_file_names_a_file_that_does_not_ship(tree: Path) -> None:
    """The general form of the bug above, over every file the edits touch.

    Not a hygiene check yet -- `release_checks.py` itself lists these names in
    BANNED_PATH_FRAGMENTS, so a content scan would flag the checker. Asserted here instead,
    where the checker is not in scope.
    """
    apply_all(tree)
    for path in sorted({r.path for r in REWRITES} | {d.path for d in SECTION_DROPS}):
        text = (tree / path).read_text()
        for dead in ("SIBLINGS.md", "siblings.lock.toml", "check_siblings.py", "docs/agents/"):
            assert dead not in text, f"{path} still points at {dead}, which never ships"


def test_the_claude_stub_loses_its_link_to_the_excluded_directory(tree: Path) -> None:
    apply_all(tree)
    assert (tree / "CLAUDE.md").read_text().strip() == "See [AGENTS.md](AGENTS.md)."


# --------------------------------------------------------------------------------------
# The manifest edit.
# --------------------------------------------------------------------------------------


def test_edit_pyproject_cuts_the_sibling_path_sources() -> None:
    edited = edit_pyproject((REPO_ROOT / "pyproject.toml").read_text())
    assert "[tool.uv.sources]" not in edited
    assert "[tool.uv]" not in edited
    assert "../aas_middleware_inf" not in edited
    assert "override-dependencies" not in edited


def test_edit_pyproject_keeps_the_force_include_that_puts_the_docs_in_the_wheel() -> None:
    """#130's stanza is not a release-time edit, and this edit must not remove it by accident."""
    edited = edit_pyproject((REPO_ROOT / "pyproject.toml").read_text())
    assert "[tool.hatch.build.targets.wheel.force-include]" in edited
    assert "AGENTS.md" in edited
    assert release_edits._MECHANICS.rstrip("/") in edited


def test_edit_pyproject_keeps_everything_else() -> None:
    original = (REPO_ROOT / "pyproject.toml").read_text()
    edited = edit_pyproject(original)
    for kept in (
        "[project]",
        "[project.scripts]",
        "[project.optional-dependencies]",
        "[dependency-groups]",
        "[tool.pytest.ini_options]",
        "[tool.mypy]",
        "[build-system]",
        "[tool.hatch.build.targets.wheel]",
        "[tool.hatch.build.targets.wheel.sources]",
    ):
        assert kept in edited


def test_edit_pyproject_leaves_valid_toml() -> None:
    import tomllib

    edited = edit_pyproject((REPO_ROOT / "pyproject.toml").read_text())
    parsed = tomllib.loads(edited)
    assert parsed["project"]["name"] == "kapps-semantic-middleware"
    assert "uv" not in parsed.get("tool", {})


def test_edit_pyproject_still_builds_a_wheel(tmp_path: Path) -> None:
    """The manifest must survive the edit as something hatchling can actually build.

    Valid TOML that hatchling rejects would fail at release time, in the middle of a run that
    has already cut a branch.
    """
    project = tmp_path / "project"
    project.mkdir()
    shutil.copytree(REPO_ROOT / "src", project / "src")
    shutil.copytree(REPO_ROOT / "demo", project / "demo")
    shutil.copytree(REPO_ROOT / "docs/mechanics", project / "docs/mechanics")
    for name in ("README.md", "LICENSE", "AGENTS.md", "CONTEXT-MAP.md"):
        shutil.copyfile(REPO_ROOT / name, project / name)
    (project / "pyproject.toml").write_text(
        edit_pyproject((REPO_ROOT / "pyproject.toml").read_text())
    )

    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list((tmp_path / "dist").glob("*.whl"))


def test_a_section_ends_at_a_shallower_heading_not_only_an_equal_one() -> None:
    """A `##` section followed by a `#` one used to swallow the rest of the file.

    The scan matched only an *exactly* equal rank. Deeper headings were skipped correctly and
    shallower ones were missed entirely, so the section never found its end, ran to EOF, and
    the replacement took every remaining line with it -- silently, in a tree whose whole review
    is a diff. It bites wherever a README and a docs copy sit one heading rank apart. Found
    during #118's release in the fork; brought back by #158.
    """
    text = (
        "## Doomed\n"
        "\n"
        "body that goes\n"
        "\n"
        "# Survivor\n"
        "\n"
        "this line must still be here\n"
    )
    drop = SectionDrop("x.md", "## Doomed", "## Replacement\n\n", "test")

    result = apply_section_drop(text, drop)

    assert "body that goes" not in result
    assert "# Survivor" in result
    assert "this line must still be here" in result
    assert result.startswith("## Replacement")


def test_a_section_still_ends_at_an_equal_heading() -> None:
    """The behaviour that was already correct, pinned so the fix cannot overshoot."""
    text = "## First\n\nbody\n\n## Second\n\nkept\n"
    drop = SectionDrop("x.md", "## First", "## New\n\n", "test")

    result = apply_section_drop(text, drop)

    assert "body" not in result
    assert "## Second" in result and "kept" in result


def test_a_deeper_heading_does_not_end_the_section() -> None:
    """A `###` inside a `##` section is part of it, and must be taken with it."""
    text = "## Outer\n\nbody\n\n### Inner\n\nalso body\n\n## Next\n\nkept\n"
    drop = SectionDrop("x.md", "## Outer", "## New\n\n", "test")

    result = apply_section_drop(text, drop)

    assert "body" not in result and "also body" not in result
    assert "### Inner" not in result
    assert "## Next" in result and "kept" in result


def test_a_hashtag_at_the_start_of_a_line_does_not_end_a_section() -> None:
    """`#nothing` is not a heading, and ending a section on one truncates the drop.

    The trailing-space check is what separates a heading from a word that happens to start
    with a hash. Without it this section would end early and leave half its body behind.
    """
    text = "## Doomed\n\nbody\n\n#nothashtag not a heading\n\nmore body\n\n# Real\n\nkept\n"
    drop = SectionDrop("x.md", "## Doomed", "## New\n\n", "test")

    result = apply_section_drop(text, drop)

    assert "body" not in result and "more body" not in result
    assert "#nothashtag" not in result
    assert "# Real" in result and "kept" in result


def test_apply_all_reads_and_writes_bytes_so_crlf_survives(tree: Path) -> None:
    """Text mode would rewrite every line ending as a side effect of editing one paragraph.

    A CRLF checkout is normal on Windows, which #113 made a first-class target. The damage is
    invisible in the working tree and enormous in the diff -- and the diff is the only review a
    release tree gets.
    """
    target = tree / "CONTEXT-MAP.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))

    apply_all(tree)

    result = target.read_bytes()
    assert b"\r\n" in result, "the file lost its CRLF endings entirely"
    # No bare LF survives except as the second half of a CRLF pair.
    assert result.replace(b"\r\n", b"") .count(b"\n") == 0
