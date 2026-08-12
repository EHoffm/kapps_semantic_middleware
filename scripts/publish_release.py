#!/usr/bin/env python3
"""Publish a reviewed release tree to the public repository.

This is the second of two scripts; `prepare_release.py` stages a filtered mirror for human review.
All work happens in a staging directory first; git is touched only after every check passes.

    python scripts/publish_release.py --repo https://github.com/circularfactory/NAME.git
                                      [--state .release-state.json] [--dry-run] [--yes]

Run from the repo root. Exit code 0 on success, non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import io
from pathlib import Path

# Import the collaborator module; it lives in the same directory.
import release_checks

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
    """Entry point; parse args and run the release publication pipeline."""
    parser = argparse.ArgumentParser(
        description="Publish a reviewed release to the public repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Public repository URL (required).",
    )
    parser.add_argument(
        "--state",
        default=".release-state.json",
        help="Path to state file from prepare_release.py (default: .release-state.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except push.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation before push.",
    )
    args = parser.parse_args(argv)

    # Step 1: Read the state file.
    state_path = REPO_ROOT / args.state
    if not state_path.exists():
        print(
            f"{RED}State file not found: {state_path}{OFF}",
            file=sys.stderr,
        )
        print(
            f"{DIM}Run prepare_release.py first:{OFF}",
            file=sys.stderr,
        )
        print("  python scripts/prepare_release.py --version N.N.N", file=sys.stderr)
        return 1

    state_text = state_path.read_text()
    state = json.loads(state_text)

    version = state.get("version")
    branch = state.get("branch")
    sha = state.get("sha")
    prepared_at = state.get("prepared_at")

    if not all([version, branch, sha, prepared_at]):
        print(
            f"{RED}State file missing required fields: version, branch, sha, prepared_at{OFF}",
            file=sys.stderr,
        )
        return 1

    print(f"{BOLD}State loaded: v{version} from {branch} @ {sha[:7]}{OFF}")

    # Step 2: Refuse a moved tip.
    # The review must be a gate, not a ceremony. If the branch tip has moved since
    # preparation, the tree a human approved is not the tree about to be published.
    # That breaks the whole point of the two-script split.
    rev_parse = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"{branch}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if rev_parse.returncode != 0:
        print(
            f"{RED}Branch {branch!r} no longer exists in the dev repo.{OFF}",
            file=sys.stderr,
        )
        return 1

    current_sha = rev_parse.stdout.strip()
    if current_sha != sha:
        print(f"{RED}Branch tip has moved since preparation.{OFF}", file=sys.stderr)
        print(f"  Recorded SHA: {sha}", file=sys.stderr)
        print(f"  Current SHA:  {current_sha}", file=sys.stderr)
        print(
            f"{DIM}Someone amended the branch after review. Re-run prepare_release.py.{OFF}",
            file=sys.stderr,
        )
        return 1

    print(f"{BOLD}Tip unchanged: reviewed tree is still at {sha[:7]}.{OFF}")

    # Step 3: Preflight the tag.
    # A release is published once. If the tag already exists in either repo, refuse.
    tag_name = f"v{version}"

    dev_tag_check = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"refs/tags/{tag_name}"],
        capture_output=True,
        text=True,
    )
    if dev_tag_check.returncode == 0:
        print(
            f"{RED}Tag {tag_name} already exists in the dev repo.{OFF}",
            file=sys.stderr,
        )
        print(f"{DIM}A release is published once. Increment the version.{OFF}", file=sys.stderr)
        return 1

    # Check public repo without cloning — use ls-remote.
    ls_remote = subprocess.run(
        ["git", "ls-remote", args.repo, f"refs/tags/{tag_name}"],
        capture_output=True,
        text=True,
    )
    if ls_remote.returncode == 0 and ls_remote.stdout.strip():
        print(
            f"{RED}Tag {tag_name} already exists in the public repo.{OFF}",
            file=sys.stderr,
        )
        print(f"{DIM}A release is published once. Increment the version.{OFF}", file=sys.stderr)
        return 1

    print(f"{BOLD}Tag {tag_name} does not exist in dev or public repo.{OFF}")

    # Step 4: Clone the public repo.
    # An empty repository is the expected first case — a clone succeeds but has no
    # commits and no checked-out branch. Handle it: determine the default branch name,
    # and if there are no commits, the first release commit becomes the root.
    clone_dir = Path(tempfile.mkdtemp(prefix="publish-release-"))
    clone_succeeded = False
    commit_made = False

    try:
        print(f"{BOLD}Cloning public repo...{OFF}")
        subprocess.run(
            ["git", "clone", "--no-tags", args.repo, str(clone_dir)],
            capture_output=True,
            text=True,
            check=True,
        )
        clone_succeeded = True

        # Determine the default branch name.
        # In an empty repo, symbolic-ref HEAD fails; fall back to init.defaultBranch config.
        symbolic_ref = subprocess.run(
            ["git", "-C", str(clone_dir), "symbolic-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        if symbolic_ref.returncode == 0:
            # refs/heads/main -> main
            default_branch = symbolic_ref.stdout.strip().replace("refs/heads/", "")
        else:
            # Empty repo or detached HEAD; check init.defaultBranch.
            config_branch = subprocess.run(
                ["git", "-C", str(clone_dir), "config", "init.defaultBranch"],
                capture_output=True,
                text=True,
            )
            if config_branch.returncode == 0 and config_branch.stdout.strip():
                default_branch = config_branch.stdout.strip()
            else:
                default_branch = "main"

        # Check if the clone has any commits.
        rev_list = subprocess.run(
            ["git", "-C", str(clone_dir), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
        )
        has_commits = rev_list.returncode == 0 and rev_list.stdout.strip() != "0"

        if not has_commits:
            print(f"{DIM}Empty repository; first release will be root commit.{OFF}")
            # Ensure we're on the default branch for the first commit.
            subprocess.run(
                ["git", "-C", str(clone_dir), "checkout", "-b", default_branch],
                capture_output=True,
                text=True,
            )
        else:
            print(f"On branch {default_branch} with existing history.")

        # Step 5: Copy the tree.
        # Export the tree at the recorded SHA from the dev repo with git archive,
        # then extract into the clone using stdlib tarfile. Delete everything in
        # the clone except .git/ first — this removes files from previous releases
        # that no longer exist in the reviewed tree.
        print(f"{BOLD}Copying reviewed tree...{OFF}")

        # Remove everything except .git/.
        for item in clone_dir.iterdir():
            if item.name != ".git":
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        # Export and extract.
        archive_proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", sha],
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(archive_proc.stdout), mode="r|") as archive:
            archive.extractall(clone_dir, filter="data")

        print(f"Tree copied from dev repo @ {sha[:7]}.")

        # Step 6: Run all five checks.
        # Unlike prepare_release.py, checks 1 and 2 are meaningful here: the clone
        # is a real git repo with the public history and the public remote.
        print(f"{BOLD}Running all five hygiene checks...{OFF}")
        violations = release_checks.run_all(clone_dir, args.repo)
        if violations:
            print(f"{RED}Release checks failed:{OFF}", file=sys.stderr)
            for violation in violations:
                print(
                    f"  {violation.check}  {violation.path}  {violation.detail}",
                    file=sys.stderr,
                )
            return 1
        print("All five checks passed.")

        # Step 7: Commit.
        # Parent is whatever the clone's branch tip already is, giving the linear
        # release line: one commit per release, and git diff v0.1.0..v0.2.0 works
        # for a stranger.
        print(f"{BOLD}Committing...{OFF}")
        subprocess.run(
            ["git", "-C", str(clone_dir), "add", "-A"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(clone_dir), "commit", "-m", f"release: v{version}"],
            check=True,
            capture_output=True,
        )
        commit_made = True
        print(f"Committed: release: v{version}")

        # Step 8: Tag.
        # Annotated tag with a message — lightweight tags carry no message and are
        # less visible in git log --tags output.
        print(f"{BOLD}Tagging...{OFF}")
        subprocess.run(
            ["git", "-C", str(clone_dir), "tag", "-a", tag_name, "-m", f"Release v{version}"],
            check=True,
            capture_output=True,
        )
        print(f"Tagged: {tag_name}")

        # Step 9: Confirm, then push.
        if args.dry_run:
            print(f"{DIM}[dry-run] Would push branch and tag to {args.repo}.{OFF}")
            tip_sha = "(not computed in dry-run)"
        else:
            # Gather summary for confirmation.
            rev_parse_head = subprocess.run(
                ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            tip_sha = rev_parse_head.stdout.strip()

            commit_subject = subprocess.run(
                ["git", "-C", str(clone_dir), "log", "-1", "--format=%s"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            file_count = len(list(clone_dir.glob("*"))) - 1  # exclude .git

            if not args.yes:
                print(f"\n{BOLD}Ready to publish:{OFF}")
                print(f"  Repo:     {args.repo}")
                print(f"  Branch:   {default_branch}")
                print(f"  Version:  {version}")
                print(f"  Commit:   {commit_subject}")
                print(f"  Files:    {file_count}")
                print(f"\n{DIM}Type the version string to confirm:{OFF}")
                confirm = input(f"  Enter '{version}': ")
                if confirm != version:
                    print(f"{RED}Confirmation failed; aborting.{OFF}", file=sys.stderr)
                    return 1

            print(f"{BOLD}Pushing...{OFF}")
            # Plain `git push`, never `--force`. The public repo is the source of truth
            # for consumers; overwriting history there would break anyone who cloned it.
            # If something went wrong, fix it with a new release, not by rewriting.
            subprocess.run(
                ["git", "-C", str(clone_dir), "push", "origin", default_branch],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(clone_dir), "push", "origin", tag_name],
                check=True,
                capture_output=True,
            )
            print("Pushed branch and tag.")

        # Step 10: Report.
        print(f"\n{GREEN}Release published.{OFF}")
        if not args.dry_run:
            print(f"Commit: {tip_sha}")
            print(f"Tag:    {tag_name}")
            print(f"URL:    {args.repo}")
            print(
                f"{DIM}Note: The tag push fires the PyPI publish workflow.{OFF}"
            )
            print(f"{DIM}That is the last irreversible act.{OFF}")

        return 0

    finally:
        # Clean up the temporary clone unless the run failed after committing.
        # In that case, leave it so a human can inspect what went wrong.
        if clone_succeeded:
            if commit_made:
                # Failed after commit; preserve for inspection.
                if not args.dry_run:
                    print(f"\n{YELLOW}Clone preserved for inspection: {clone_dir}{OFF}")
            else:
                # No commit made; safe to clean up.
                shutil.rmtree(clone_dir)
        else:
            # Clone failed; nothing to clean.
            pass

    # After successful non-dry-run publish, delete the state file.
    # It describes a release that has now happened; leaving it invites a second run.
    if not args.dry_run and commit_made:
        state_path.unlink()
        print(f"{DIM}State file deleted.{OFF}")


if __name__ == "__main__":
    raise SystemExit(main())

