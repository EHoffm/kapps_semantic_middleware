#!/usr/bin/env python3
"""What reaches the public release tree, and what never does (#110, #129).

An **allowlist, not a deny list**: #110 chose it because a deny list fails open -- a new
agent-facing file at the root ships unless someone remembers to exclude it.

This goes one step further than #110 described. Every tracked path must match a rule, and a
path matching none is an **error that stops the release**, not a silent exclusion. A deny list
fails open, a plain allowlist fails closed in one direction only (a newly added file that
*should* ship silently does not), and neither is what you want from a gate that runs a few
times a year. `docs/site/` is the live example: it arrives with #116, on a branch that did not
exist when the allowlist was written, and it must ship. Under a plain allowlist the docs would
have quietly gone missing from the release.

This module never ships. It runs from a dev checkout, driven by `prepare_release.py`.
"""

from __future__ import annotations

from typing import NamedTuple


class Rule(NamedTuple):
    """One classification rule.

    ``prefix`` matches a repo-relative POSIX path either exactly (a file) or as a directory
    prefix (when it ends in ``/``).
    """

    prefix: str
    ships: bool
    why: str


class Unclassified(LookupError):
    """A tracked path matches no rule.

    Raised rather than defaulted, in either direction. Whoever added the path decides where it
    belongs, at the moment the release stops -- which is cheap -- rather than a reader of the
    public repo discovering the answer, which is not.
    """


# Most specific first: `classify` takes the first match, so a nested exclusion must precede
# the directory that otherwise carries it.
RULES: tuple[Rule, ...] = (
    # -- nested exclusions inside directories that otherwise ship ----------------------------
    Rule(
        "src/kapps_semantic_middleware/docs/adr/",
        False,
        "32 decision records. Dev-repo genre: why we chose this over that.",
    ),
    Rule(
        "src/kapps_semantic_middleware/shacl_interop/docs/adr/",
        False,
        "The 33rd record, one directory deeper. A glob written for the first misses it.",
    ),
    Rule(
        "examples/docs/adr/",
        False,
        "The leak #129 names: examples/ ships wholesale, so this record rode along.",
    ),
    Rule(
        "tests/test_release_allowlist.py",
        False,
        "Tests this module, which does not ship. Would fail on import in the public repo.",
    ),
    Rule(
        "tests/test_release_edits.py",
        False,
        "Tests release_edits, which does not ship, and quotes the record paths check 5 bans.",
    ),
    Rule(
        "tests/test_release_wheel.py",
        False,
        "Tests prepare_release, which does not ship.",
    ),
    Rule(
        "scripts/release_checks.py",
        True,
        "The one file out of scripts/ that ships: .github/workflows/hygiene.yml runs it.",
    ),
    # -- docs/ is split down the middle -------------------------------------------------------
    Rule("docs/mechanics/", True, "#130's seven pages: the mechanics, with the rationale removed."),
    Rule("docs/site/", True, "#116's Sphinx source. The Pages workflow builds it in the release repo."),
    Rule("docs/adr/", False, "The four root records."),
    Rule("docs/prd/", False, "Requirements this project places on sibling repos."),
    Rule("docs/research/", False, "Working notes."),
    Rule("docs/agents/", False, "Dev-side agent configuration. Named by check 3."),
    Rule("docs/brownfield-gap-analysis.md", False, "A dev-side analysis document."),
    # -- dev-only ------------------------------------------------------------------------------
    Rule("scripts/", False, "check.sh and check_siblings.py drive a dev checkout, and the release scripts run from one."),
    Rule(".github/", False, "Replaced, not copied: the release repo's workflows are tag->PyPI, CI, Pages and hygiene."),
    Rule(".claude/", False, "Agent configuration. Named by check 3."),
    Rule(".vscode/", False, "Editor settings."),
    Rule("SIBLINGS.md", False, "Names the private host. Named by checks 3 and 4."),
    Rule("siblings.lock.toml", False, "Same. Names the private host."),
    # -- ships ----------------------------------------------------------------------------------
    Rule("src/", True, "The library."),
    Rule("tests/", True, "#123 runs them as the release repo's CI."),
    Rule("demo/", True, "The factory demo, which the wheel ships as `.demonstrations`."),
    Rule("examples/", True, "Scenario 1 and scenario 2 notebooks."),
    Rule("docker/", True, "#114's compose file. The destination promises one `docker compose up`."),
    Rule("AGENTS.md", True, "#130. The consuming agent's entry point."),
    Rule("CLAUDE.md", True, "Ships as the one-line stub. #110 admits it by name; check 3 allows it."),
    Rule("CONTEXT-MAP.md", True, "Navigation, not reasoning."),
    Rule("README.md", True, "The human stranger's front door."),
    Rule("LICENSE", True, "MIT, added while charting map #108."),
    Rule("pyproject.toml", True, "Edited at release time: the sibling path sources are cut."),
    Rule("uv.lock", True, "Ships as-is."),
    Rule(".gitignore", True, "Ships as-is."),
    Rule(".python-version", True, "Ships as-is."),
    Rule(".env.example", True, "The GRAPHDB_* variables the examples and the demo read."),
)


class Plan(NamedTuple):
    """The split of a tracked file list into what ships and what does not."""

    ships: list[str]
    excluded: list[str]


def classify(relpath: str) -> Rule:
    """Return the first rule matching ``relpath``.

    Raises ``Unclassified`` when nothing matches, which stops the release.
    """
    for rule in RULES:
        if rule.prefix.endswith("/"):
            if relpath.startswith(rule.prefix):
                return rule
        elif relpath == rule.prefix:
            return rule
    raise Unclassified(
        f"{relpath} matches no rule in RULES. Add one saying whether it ships and why: "
        "a release must not guess."
    )


def plan(relpaths: list[str]) -> Plan:
    """Split tracked paths into what ships and what does not.

    Raises ``Unclassified`` on the first unrecognised path, naming it.
    """
    ships: list[str] = []
    excluded: list[str] = []
    for relpath in sorted(relpaths):
        (ships if classify(relpath).ships else excluded).append(relpath)
    return Plan(ships, excluded)
