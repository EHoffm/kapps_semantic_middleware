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
import re
import shutil
import subprocess
import sys
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
        subprocess.run(
            ["tar", "-x", "-C", str(staging)],
            input=archive_proc.stdout,
            check=True,
        )

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

            # Build the forbidden prefix from DEAD_REFERENCE_DIRS without spelling it out.
            # DEAD_REFERENCE_DIRS[0] is something like "src/kapps_semantic_middleware/docs/adr/",
            # so we strip "src/" and use the rest as the wheel-entry prefix.
            forbidden_repo_path = release_checks.DEAD_REFERENCE_DIRS[0]
            forbidden_prefix = "/".join(forbidden_repo_path.split("/")[1:])

            wheel_problems: list[str] = []

            # No entry may contain the decision-record directory.
            for entry in entries:
                if entry.startswith(forbidden_prefix):
                    wheel_problems.append(f"forbidden: {entry}")

            # Required entries must be present.
            package = "kapps_semantic_middleware"
            required = [
                f"{package}/AGENTS.md",
                f"{package}/CONTEXT-MAP.md",
            ]
            for req in required:
                if req not in entries:
                    wheel_problems.append(f"missing: {req}")

            # At least one mechanics file must exist.
            mechanics_entries = [
                e for e in entries if e.startswith(f"{package}/docs/mechanics/")
            ]
            if not mechanics_entries:
                wheel_problems.append("missing: at least one mechanics page")

            if wheel_problems:
                print(f"{RED}Wheel content violations:{OFF}", file=sys.stderr)
                for v in wheel_problems:
                    print(f"  {v}", file=sys.stderr)
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
                    [str(python_exe), "-c", f"import {package}"],
                    check=True,
                    capture_output=True,
                )
                print(f"Import of {package} succeeded in isolated venv.")
            finally:
                shutil.rmtree(venv_dir)

        # Step 7: Run the five checks over the staging tree.
        print(f"{BOLD}Running release checks...{OFF}")
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
            # Delete any existing local prepare-release branch.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "branch", "-D", "prepare-release"],
                capture_output=True,
            )

            # Create fresh branch from --from.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "checkout", "-b", "prepare-release", args.from_branch],
                check=True,
                capture_output=True,
            )

            # Remove every tracked file from the working tree.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rm", "-rf", "."],
                check=True,
                capture_output=True,
            )

            # Copy the staging tree in.
            for item in staging.iterdir():
                dest = REPO_ROOT / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            # git add -A and commit.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "add", "-A"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "commit", "-m", f"release: v{args.version}"],
                check=True,
                capture_output=True,
            )

            # Step 9: Push prepare-release to origin.
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "push", "-f", "origin", "prepare-release"],
                check=True,
                capture_output=True,
            )

            # Get the tip SHA.
            tip_sha = (
                subprocess.run(
                    ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
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
