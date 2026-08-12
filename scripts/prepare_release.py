#!/usr/bin/env python3
"""Stage a filtered mirror of the dev repo onto `prepare-release` for human review.

This is the first of two scripts; `publish_release.py` later copies the reviewed tree into the
public repo. All work happens in a staging directory first; git is touched only after every
check passes.

    python scripts/prepare_release.py --version 0.1.0 [--from main] [--dry-run]
                                      [--skip-cross-check] [--keep-staging]

Run from the repo root. Exit code 0 on success, non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Import the three collaborator modules; they live in the same directory.
import release_allowlist
import release_checks
import release_edits

GREEN, YELLOW, RED, DIM, BOLD, OFF = (
    "\033[32m",
    "\033[33m",
    "\033[31m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)

REPO_ROOT = Path(__file__).resolve().parents[1]


PACKAGE = "kapps_semantic_middleware"


def wheel_problems(entries: list[str], package: str = PACKAGE) -> list[str]:
    """Judge a built wheel's entry list. Empty means the wheel is what #129 asked for.

    Two assertions, and they are twins: the decision records must be **gone**, and the pages
    #130 wrote to replace them must be **present**. Only checking the first would let a wheel
    pass that had dropped the records and the replacements together, which is the worse
    outcome -- a consuming agent reading the installed tree would get `CONTEXT.md`'s citations
    and nothing that answers them.

    Matched as a **substring, not a prefix**. There are two record directories at different
    depths -- `<pkg>/docs/adr/` and `<pkg>/shacl_interop/docs/adr/` -- and #129 names that
    shape explicitly as the trap: a rule written for the first silently misses the second. A
    prefix test misses both, because every wheel entry starts with the package name.
    """
    problems: list[str] = []

    for dead in release_checks.DEAD_REFERENCE_DIRS:
        problems.extend(f"forbidden: {entry}" for entry in entries if dead in entry)

    for required in (f"{package}/AGENTS.md", f"{package}/CONTEXT-MAP.md"):
        if required not in entries:
            problems.append(f"missing: {required}")

    if not any(entry.startswith(f"{package}/docs/mechanics/") for entry in entries):
        problems.append("missing: every mechanics page")

    return problems


def main(argv: list[str] | None = None) -> int:
    """Entry point; parse args and run the release preparation pipeline."""
    parser = argparse.ArgumentParser(
        description="Stage a filtered mirror for release review.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version (N.N.N); must match pyproject.toml.",
    )
    parser.add_argument(
        "--from",
        dest="from_branch",
        default="main",
        help="Branch to cut from (default: main).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except create the branch and push.",
    )
    parser.add_argument(
        "--skip-cross-check",
        action="store_true",
        help="Skip the wheel build and test run.",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Leave the staging directory in place and print its path.",
    )
    args = parser.parse_args(argv)

    # Validate version format.
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        print(f"{RED}Version must be N.N.N, got: {args.version}{OFF}", file=sys.stderr)
        return 1

    # Check version matches pyproject.toml.
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        print(f"{RED}pyproject.toml not found{OFF}", file=sys.stderr)
        return 1
    manifest_text = pyproject.read_text()
    manifest_data = tomllib.loads(manifest_text)
    manifest_version = manifest_data.get("project", {}).get("version")
    if manifest_version != args.version:
        print(
            f"{RED}Version mismatch: --version={args.version}, "
            f"pyproject.toml says {manifest_version}{OFF}",
            file=sys.stderr,
        )
        return 1

    # Step 1: Preflight — no uncommitted changes to tracked files.
    #
    # Untracked files are reported but not fatal. Step 2 stages the tree with `git archive`,
    # which reads the commit and not the working directory, so an untracked file cannot reach
    # a release however messy the checkout is. A *modified* tracked file is different: it means
    # the tree the developer is looking at is not the tree that would ship, and reviewing a
    # diff under that illusion is exactly what this gate exists to prevent.
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    modified = [ln for ln in status.stdout.splitlines() if ln and not ln.startswith("??")]
    untracked = [ln for ln in status.stdout.splitlines() if ln.startswith("??")]
    if modified:
        print(f"{RED}Tracked files have uncommitted changes; commit or stash them first:{OFF}")
        for line in modified:
            print(f"  {line}")
        return 1
    if untracked:
        print(f"{YELLOW}Note: {len(untracked)} untracked path(s) present, and ignored.{OFF}")
        for line in untracked:
            print(f"  {DIM}{line}{OFF}")

    # Step 1: Preflight — --from branch must exist.
    rev_parse = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", args.from_branch],
        capture_output=True,
        text=True,
    )
    if rev_parse.returncode != 0:
        print(f"{RED}Branch {args.from_branch!r} does not exist.{OFF}", file=sys.stderr)
        return 1

    print(f"{BOLD}Preflight passed.{OFF}")

    # Create staging directory.
    staging = Path(tempfile.mkdtemp(prefix="prepare-release-"))
    try:
        # Step 2: Stage the tree via git archive.
        # This gives exactly the tracked files at that commit, with no .git and no untracked
        # residue — a stray local file cannot reach a release.
        archive_proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", args.from_branch],
            capture_output=True,
            check=True,
        )
        # Extracted with the stdlib rather than an external `tar`, which Windows has no
        # guarantee of. Map #108 makes Windows first-class for everything a user touches, and
        # a release mechanism that dies before its first hygiene check is the worst place to
        # discover a missing tool.
        with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout), mode="r|") as archive:
            archive.extractall(staging, filter="data")

        # Gather all relative paths in staging for the allowlist.
        relpaths = [
            str(p.relative_to(staging))
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        ]

        # Step 3: Apply the allowlist.
        try:
            plan_result = release_allowlist.plan(relpaths)
        except release_allowlist.Unclassified as e:
            print(f"{RED}{e}{OFF}", file=sys.stderr)
            return 1

        # Delete excluded paths and prune empty directories.
        for excluded in plan_result.excluded:
            (staging / excluded).unlink()

        # Prune empty directories bottom-up.
        for dirpath in sorted(
            (d for d in staging.rglob("*") if d.is_dir()),
            reverse=True,
        ):
            if not any(dirpath.iterdir()):
                dirpath.rmdir()

        print(
            f"Allowlist: {len(plan_result.ships)} files ship, "
            f"{len(plan_result.excluded)} excluded."
        )

        # Step 4: Apply the release-time edits.
        changed = release_edits.apply_all(staging)
        print(f"Edits applied to {len(changed)} file(s): {', '.join(changed)}")

        # Rewrite pyproject.toml to cut sibling path sources.
        pyproject_staging = staging / "pyproject.toml"
        edited_manifest = release_edits.edit_pyproject(pyproject_staging.read_text())
        pyproject_staging.write_text(edited_manifest)
        print("pyproject.toml: sibling path sources removed.")

        # Step 5: Write the release workflows.
        workflows_dir = staging / ".github" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        hygiene_path = workflows_dir / "hygiene.yml"
        hygiene_content = (
            "# This workflow is the backstop for commits made directly in the public repo.\n"
            "# The pre-push gate in the dev checkout cannot see those commits, so the public\n"
            "# repo needs its own CI that runs the same hygiene checks.\n"
            "\n"
            "name: hygiene\n"
            "\n"
            "on:\n"
            "  push:\n"
            "  pull_request:\n"
            "\n"
            "jobs:\n"
            "  hygiene:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          fetch-depth: 0\n"
            "      - name: Run the release hygiene checks\n"
            "        run: python scripts/release_checks.py .\n"
        )
        hygiene_path.write_text(hygiene_content)
        print("Wrote .github/workflows/hygiene.yml")
        print(
            f"{DIM}Note: Three workflows still owed — PyPI publish, CI, Pages.{OFF}"
        )

        # Step 6: Cross-check (unless skipped).
        if not args.skip_cross_check:
            print(f"{BOLD}Cross-check: building wheel...{OFF}")
            subprocess.run(
                ["uv", "build", "--wheel"],
                cwd=staging,
                capture_output=True,
                text=True,
                check=True,
            )

            # Find the wheel.
            dist_dir = staging / "dist"
            wheels = list(dist_dir.glob("*.whl"))
            if not wheels:
                print(f"{RED}No wheel found in {dist_dir}{OFF}", file=sys.stderr)
                return 1
            wheel_path = wheels[0]

            # Inspect wheel contents.
            with zipfile.ZipFile(wheel_path, "r") as whl:
                entries = whl.namelist()

            problems = wheel_problems(entries)
            if problems:
                print(f"{RED}Wheel content violations:{OFF}", file=sys.stderr)
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                return 1

            print(f"Wheel has {len(entries)} entries; content checks passed.")

            # Install the wheel into a throwaway venv and import the package.
            # Nothing is downstream of this repo, so this self-check is the whole cross-check here.
            venv_dir = Path(tempfile.mkdtemp(prefix="cross-check-venv-"))
            try:
                subprocess.run(
                    ["uv", "venv", str(venv_dir)],
                    check=True,
                    capture_output=True,
                )
                # `uv` is not installed *into* a venv -- it is the tool driving one, and it is
                # told which interpreter to target with `--python`. Windows puts that
                # interpreter under Scripts/ rather than bin/, and #113 made Windows a
                # first-class target for everything a user touches.
                python_exe = venv_dir / "bin" / "python"
                if not python_exe.exists():
                    python_exe = venv_dir / "Scripts" / "python.exe"
                subprocess.run(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python",
                        str(python_exe),
                        str(wheel_path),
                    ],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [str(python_exe), "-c", f"import {PACKAGE}"],
                    check=True,
                    capture_output=True,
                )
                print(f"Import of {PACKAGE} succeeded in isolated venv.")
            finally:
                shutil.rmtree(venv_dir)

        # Step 7: checks 3-5 over the staging tree. Not 1 and 2: there is no git repo
        # here yet (the branch is cut in step 8), so remotes and trailers have nothing to
        # read. publish_release.py runs the full five against the release clone, which is
        # where a wrong remote or a stray trailer could actually do damage.
        print(f"{BOLD}Running tree checks (3-5)...{OFF}")
        violations = release_checks.run_tree_checks(staging)
        if violations:
            print(f"{RED}Release checks failed:{OFF}", file=sys.stderr)
            for violation in violations:
                print(
                    f"  {violation.check}  {violation.path}  {violation.detail}",
                    file=sys.stderr,
                )
            return 1
        print("All release checks passed.")

        # Step 8: Cut the branch.
        if args.dry_run:
            print(f"{DIM}[dry-run] Would delete existing prepare-release branch.{OFF}")
            print(f"{DIM}[dry-run] Would create prepare-release from {args.from_branch}.{OFF}")
            print(f"{DIM}[dry-run] Would copy staging tree and commit.{OFF}")
            tip_sha = "(not computed in dry-run)"
        else:
            # The branch is built with plumbing, so the developer's working tree is never
            # touched. The obvious implementation -- checkout -b, `git rm -rf .`, copy the
            # staging tree in, commit -- leaves the checkout sitting on `prepare-release` with
            # the *filtered* tree in it. That is alarming on its own (half of `scripts/` and
            # every decision record appear to have been deleted), and it is worse than
            # alarming: the next command a developer runs, including `publish_release.py`, is
            # read out of a tree that no longer contains it. Found by exactly that accident.
            #
            # Writing a tree from a scratch index costs three plumbing calls and cannot do any
            # of it: nothing is checked out, nothing is removed, HEAD does not move.
            index_file = staging.parent / f"{staging.name}.index"
            git_env = {
                **os.environ,
                "GIT_INDEX_FILE": str(index_file),
                "GIT_WORK_TREE": str(staging),
            }

            def git_plumbing(*args: str) -> str:
                return subprocess.run(
                    ["git", "-C", str(REPO_ROOT), *args],
                    env=git_env,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()

            git_plumbing("add", "-A")
            tree_sha = git_plumbing("write-tree")

            # Parent is the branch being released from, so the release branch reads as a diff
            # against it -- which is the whole point of stopping here for review.
            parent_sha = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", args.from_branch],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            tip_sha = git_plumbing(
                "commit-tree", tree_sha, "-p", parent_sha, "-m", f"release: v{args.version}"
            )
            git_plumbing("update-ref", "refs/heads/prepare-release", tip_sha)
            index_file.unlink(missing_ok=True)

            # Step 9: push the review branch to the DEV repo. Force is acceptable here and
            # only here: `prepare-release` is regenerated from scratch every release and holds
            # nothing anyone should build on. Nothing in publish_release.py ever force-pushes.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "push", "-f", "origin", "prepare-release"],
                check=True,
                capture_output=True,
            )

        # Step 10: Record the tip.
        release_state = {
            "version": args.version,
            "branch": "prepare-release",
            "sha": tip_sha,
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path = REPO_ROOT / ".release-state.json"
        state_path.write_text(json.dumps(release_state, indent=2) + "\n")

        print(f"\n{GREEN}Release prepared on branch prepare-release.{OFF}")
        print(f"Tip SHA: {tip_sha}")
        print(f"{DIM}Reminder: .release-state.json must be in .gitignore.{OFF}")
        print("\nNext command after review:")
        print("  python scripts/publish_release.py")

        return 0

    finally:
        if not args.keep_staging:
            shutil.rmtree(staging)
        else:
            print(f"\nStaging directory preserved: {staging}")


if __name__ == "__main__":
    raise SystemExit(main())
