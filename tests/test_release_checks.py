"""The five hygiene checks that gate a public release (#129).

Every test here plants a violation and asserts the check catches it, which is the acceptance
criterion #129 states: "Each of the five checks fails the run when violated. Probed one at a
time."

**No banned literal appears in this file.** The checks scan the whole shipped tree, and the
allowlist ships `tests/` -- so a test that spelled out either banned value would be caught by the
very check it exercises. The constants are imported from the module under test instead, which
also means a test cannot drift from the value the check actually uses.

The first draft of this docstring quoted both values while explaining why not to, and
`prepare_release.py` failed on it -- the same trap `AGENTS.md` fell into, caught the same way.
Prose about a banned string is still the banned string.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import release_checks
from release_checks import (
    Violation,
    check_paths,
    check_references,
    check_remotes,
    check_secrets,
    check_trailers,
    run_tree_checks,
)

ORIGIN = "https://github.com/circularfactory/kapps_semantic_middleware.git"


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo``, with an identity so commits work on a bare runner."""
    out = subprocess.run(
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
    return out.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one clean commit and the circularfactory origin."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_text("# a release\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "release: v0.1.0")
    _git(root, "remote", "add", "origin", ORIGIN)
    return root


def _names(violations: list[Violation]) -> set[str]:
    return {v.path for v in violations}


# --------------------------------------------------------------------------------------
# The module must not contain the literals it bans, or it fails its own scan.
#
# `release_checks.py` ships to the public repo, where the hygiene workflow runs it over the
# tree it is sitting in. Assembling the literals from fragments is what lets checks 4 and 5
# stay absolute -- zero exemptions, no self-skip. These two tests are the guard on that: they
# fail the moment someone "tidies" a concatenation back into a plain string.
# --------------------------------------------------------------------------------------


def test_module_source_contains_no_private_host_literal() -> None:
    source = Path(release_checks.__file__).read_text()
    assert release_checks.PRIVATE_HOST not in source


def test_module_source_contains_no_record_path_literal() -> None:
    source = Path(release_checks.__file__).read_text()
    for fragment in release_checks.DEAD_REFERENCE_DIRS:
        assert fragment not in source


def test_constants_are_the_values_we_mean() -> None:
    assert release_checks.PRIVATE_HOST == "gitlab" + "." + "kit" + "." + "edu"
    assert set(release_checks.DEAD_REFERENCE_DIRS) == {
        "docs/" + "adr/",
        "docs/" + "prd/",
    }


# --------------------------------------------------------------------------------------
# Check 1 -- remotes. Only the circularfactory origin may be configured.
# --------------------------------------------------------------------------------------


def test_check_remotes_passes_with_only_the_release_origin(repo: Path) -> None:
    assert check_remotes(repo, ORIGIN) == []


def test_check_remotes_tolerates_a_missing_dot_git_suffix(repo: Path) -> None:
    _git(repo, "remote", "set-url", "origin", ORIGIN.removesuffix(".git"))
    assert check_remotes(repo, ORIGIN) == []


def test_check_remotes_catches_a_second_remote(repo: Path) -> None:
    _git(repo, "remote", "add", "dev", "https://github.com/EHoffm/kapps_semantic_middleware.git")
    violations = check_remotes(repo, ORIGIN)
    assert violations
    assert any("dev" in v.detail for v in violations)


def test_check_remotes_catches_a_wrong_origin(repo: Path) -> None:
    _git(repo, "remote", "set-url", "origin", "https://github.com/EHoffm/kapps_semantic_middleware.git")
    assert check_remotes(repo, ORIGIN)


def test_check_remotes_catches_no_origin_at_all(repo: Path) -> None:
    _git(repo, "remote", "remove", "origin")
    assert check_remotes(repo, ORIGIN)


# --------------------------------------------------------------------------------------
# Check 2 -- trailers. No agent co-authorship in the public log.
# --------------------------------------------------------------------------------------


def test_check_trailers_passes_on_a_clean_log(repo: Path) -> None:
    assert check_trailers(repo) == []


def test_check_trailers_catches_a_claude_coauthor(repo: Path) -> None:
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "feat: a thing\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>",
    )
    violations = check_trailers(repo)
    assert len(violations) == 1


def test_check_trailers_catches_a_generated_with_line(repo: Path) -> None:
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: b\n\nGenerated with Claude Code")
    assert check_trailers(repo)


def test_check_trailers_is_case_insensitive(repo: Path) -> None:
    (repo / "c.txt").write_text("c\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: c\n\nco-authored-by: CLAUDE <x@y.z>")
    assert check_trailers(repo)


def test_check_trailers_names_the_offending_commit(repo: Path) -> None:
    (repo / "d.txt").write_text("d\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: d\n\nCo-Authored-By: Claude <x@y.z>")
    sha = _git(repo, "rev-parse", "HEAD").strip()
    violations = check_trailers(repo)
    assert any(sha.startswith(v.detail.split()[0]) or v.detail.startswith(sha[:7]) for v in violations)


def test_check_trailers_scans_the_whole_history_not_just_the_tip(repo: Path) -> None:
    (repo / "e.txt").write_text("e\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: e\n\nCo-Authored-By: Claude <x@y.z>")
    (repo / "f.txt").write_text("f\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: f")
    assert check_trailers(repo)


def test_check_trailers_does_not_fire_on_a_human_coauthor(repo: Path) -> None:
    (repo / "g.txt").write_text("g\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: g\n\nCo-Authored-By: Soeren Weindel <s@kit.edu>")
    assert check_trailers(repo) == []


# --------------------------------------------------------------------------------------
# Check 3 -- paths. Named dev-only files must not exist in the tree.
# --------------------------------------------------------------------------------------


def test_check_paths_passes_on_a_clean_tree(repo: Path) -> None:
    assert check_paths(repo) == []


@pytest.mark.parametrize(
    "relpath",
    [
        "docs/agents/issue-tracker.md",
        ".claude/settings.json",
        "SIBLINGS.md",
        "siblings.lock.toml",
        "scripts/check_siblings.py",
    ],
)
def test_check_paths_catches_each_banned_path(repo: Path, relpath: str) -> None:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n")
    violations = check_paths(repo)
    assert _names(violations) == {relpath}


def test_check_paths_allows_claude_md_because_it_ships_as_the_stub(repo: Path) -> None:
    """#110's allowlist admits `CLAUDE.md` by name: it ships as the one-line AGENTS.md stub."""
    (repo / "CLAUDE.md").write_text("See AGENTS.md.\n")
    assert check_paths(repo) == []


def test_check_paths_ignores_the_git_directory(repo: Path) -> None:
    """`.git/` holds hooks and config that are not part of the published tree."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "SIBLINGS.md").write_text("not shipped\n")
    assert check_paths(repo) == []


# --------------------------------------------------------------------------------------
# Check 4 -- secrets. The private host must appear nowhere.
# --------------------------------------------------------------------------------------


def test_check_secrets_passes_on_a_clean_tree(repo: Path) -> None:
    assert check_secrets(repo) == []


def test_check_secrets_catches_the_private_host(repo: Path) -> None:
    (repo / "notes.md").write_text(f"clone from https://{release_checks.PRIVATE_HOST}/kit/x.git\n")
    assert _names(check_secrets(repo)) == {"notes.md"}


def test_check_secrets_scans_source_files_too(repo: Path) -> None:
    (repo / "mod.py").write_text(f'URL = "{release_checks.PRIVATE_HOST}"\n')
    assert _names(check_secrets(repo)) == {"mod.py"}


def test_check_secrets_skips_binary_files(repo: Path) -> None:
    """A PNG containing the byte sequence by chance is not a leak, and must not crash the scan."""
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00" + release_checks.PRIVATE_HOST.encode())
    assert check_secrets(repo) == []


def test_check_secrets_ignores_the_git_directory(repo: Path) -> None:
    (repo / ".git" / "config").write_text(f"url = {release_checks.PRIVATE_HOST}\n")
    assert check_secrets(repo) == []


# --------------------------------------------------------------------------------------
# Check 5 -- references. No shipped file points at a decision-record directory.
#
# Both shapes fail: a full path with a filename, and a bare directory named in prose.
# Settled with Etienne 2026-08-12 -- a public README describing a folder that is not there
# makes the release look broken rather than deliberately scoped.
# --------------------------------------------------------------------------------------


def test_check_references_passes_on_a_clean_tree(repo: Path) -> None:
    assert check_references(repo) == []


def test_check_references_catches_a_full_record_path(repo: Path) -> None:
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (repo / "CONTEXT.md").write_text(f"See `src/kapps_semantic_middleware/{adr}0004-endpoint.md`.\n")
    assert _names(check_references(repo)) == {"CONTEXT.md"}


def test_check_references_catches_a_bare_directory_named_in_prose(repo: Path) -> None:
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (repo / "README.md").write_text(f"| `{adr}` | Root records. |\n")
    assert _names(check_references(repo)) == {"README.md"}


def test_check_references_catches_the_requirements_directory_too(repo: Path) -> None:
    prd = release_checks.DEAD_REFERENCE_DIRS[1]
    (repo / "CONTEXT-MAP.md").write_text(f"- [Module Requirements](./{prd})\n")
    assert _names(check_references(repo)) == {"CONTEXT-MAP.md"}


def test_check_references_allows_a_bare_citation(repo: Path) -> None:
    """#130 measured the difference: an agent chased 3 of 5 full paths and none of 85 citations.

    The path form reads as followable, the citation as provenance -- so the citation stays.
    """
    (repo / "CONTEXT.md").write_text("Registration is ADR 0012; see also root ADR 0001.\n")
    assert check_references(repo) == []


def test_check_references_catches_a_source_file_docstring(repo: Path) -> None:
    """Not only glossaries. `shape_from_typehints.py` carries two such paths in its docstring."""
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    mod = repo / "shape_from_typehints.py"
    mod.write_text(f'"""Scaffolding. See {adr}0001-shacl.md for context."""\n')
    assert _names(check_references(repo)) == {"shape_from_typehints.py"}


def test_check_references_skips_binary_files(repo: Path) -> None:
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (repo / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00" + adr.encode())
    assert check_references(repo) == []


def test_check_references_ignores_the_git_directory(repo: Path) -> None:
    adr = release_checks.DEAD_REFERENCE_DIRS[0]
    (repo / ".git" / "description").write_text(f"{adr}\n")
    assert check_references(repo) == []


# --------------------------------------------------------------------------------------
# The runner the CI backstop calls.
# --------------------------------------------------------------------------------------


def test_run_tree_checks_covers_three_four_and_five_but_not_the_git_ones(repo: Path) -> None:
    """The public workflow runs checks 2-5; 1 is about a local clone and means nothing in CI."""
    (repo / "SIBLINGS.md").write_text("x\n")
    (repo / "leak.md").write_text(release_checks.PRIVATE_HOST + "\n")
    (repo / "dead.md").write_text(release_checks.DEAD_REFERENCE_DIRS[1] + "\n")
    violations = run_tree_checks(repo)
    assert _names(violations) == {"SIBLINGS.md", "leak.md", "dead.md"}


def test_run_tree_checks_is_empty_on_a_clean_tree(repo: Path) -> None:
    assert run_tree_checks(repo) == []


def test_this_repos_own_scripts_dir_holds_the_checker_where_the_allowlist_expects_it() -> None:
    """The allowlist ships exactly one file out of `scripts/`. If this module moves, that entry
    is stale and the public workflow breaks -- so the location is asserted, not assumed."""
    root = Path(__file__).resolve().parents[1]
    assert Path(release_checks.__file__).resolve() == root / "scripts" / "release_checks.py"
