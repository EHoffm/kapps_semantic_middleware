#!/usr/bin/env python3
"""The edits applied to the release tree, and only to the release tree (#110, #129).

Every edit here **removes a fact that is only true in a dev checkout**. That is the test #110
set for what belongs in this file rather than in the dev manifest: the sibling path sources
point at checkouts a stranger does not have, and the decision records are a dev-repo genre. The
`force-include` stanza that puts `AGENTS.md` and `docs/mechanics/` into the wheel is the
counter-example -- it is equally true in both trees, so #130 put it in `pyproject.toml`
permanently rather than here.

**The rewrites are deliberately brittle.** Each one is an exact string match that must hit
exactly once. When someone rewords a glossary, the rewrite stops matching and
`tests/test_release_edits.py` fails -- in a test run, on a normal working day, naming the file.
The alternative is a fuzzy rewrite that silently stops firing and leaves a dead pointer in a
published release, which check 5 would then catch far later and with far less context. Brittle
and loud beats tolerant and quiet for something that runs a few times a year.

This module never ships. It runs from a dev checkout, driven by `prepare_release.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class Rewrite(NamedTuple):
    """An exact-match substitution in one shipped file."""

    path: str
    old: str
    new: str
    why: str


class SectionDrop(NamedTuple):
    """Replace a whole markdown section, from its heading to the next heading of equal rank."""

    path: str
    heading: str
    replacement: str
    why: str


_MECHANICS = "docs/mechanics/"

REWRITES: tuple[Rewrite, ...] = (
    # -- the five glossaries -------------------------------------------------------------------
    Rewrite(
        "examples/CONTEXT.md",
        "Self-contained, runnable Jupyter notebooks demonstrate Core Middleware end-to-end (see\n"
        "`examples/docs/adr/0001-self-contained-example-notebooks.md`). Seed-data/ontology-provisioning\n"
        "logic makes each one reproducible against a dummy repository, rather than production\n"
        "knowledge-graph state.",
        "Self-contained, runnable Jupyter notebooks demonstrate Core Middleware end-to-end.\n"
        "Seed-data/ontology-provisioning logic makes each one reproducible against a dummy\n"
        "repository, rather than production knowledge-graph state.",
        "The record it cites is the examples/ leak, which the allowlist now prunes.",
    ),
    Rewrite(
        "src/kapps_semantic_middleware/CONTEXT.md",
        'being present is a deliberate divergence from the paper\'s literal "address on Service only"\n'
        "wording — see\n"
        "`src/kapps_semantic_middleware/docs/adr/0004-endpoint-on-service-and-workflow.md`.",
        'being present is a deliberate divergence from the paper\'s literal "address on Service only"\n'
        'wording — see the "Address and endpoint" section of\n'
        f"`{_MECHANICS}02-workflow-registration.md`.",
        "ADR 0004's subject, per AGENTS.md's own mapping of records to mechanics pages.",
    ),
    Rewrite(
        "src/kapps_semantic_middleware/CONTEXT.md",
        "without going around the OGM's validated write path. See\n"
        "`src/kapps_semantic_middleware/docs/adr/0006-knowledge-graph-connector.md`.",
        'without going around the OGM\'s validated write path. See "The graph-facing connector"\n'
        f"in `{_MECHANICS}04-connector-binding.md`.",
        "ADR 0006's subject, per the same mapping.",
    ),
    Rewrite(
        "src/kapps_semantic_middleware/shacl_interop/CONTEXT.md",
        "Temporary scaffolding (see\n"
        "`src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`)\n"
        "that generates\n"
        "and parses the SHACL shapes describing a Workflow or StateProperty class's precondition/\n"
        "outcome, in place of the native `kapps_ogm` support this logic properly belongs in (see\n"
        "`docs/prd/kapps-ogm-shacl-support.md` at the repo root). Deliberately kept separate from Core",
        "Temporary scaffolding that generates\n"
        "and parses the SHACL shapes describing a Workflow or StateProperty class's precondition/\n"
        "outcome, in place of the native `kapps_ogm` support this logic properly belongs in.\n"
        "Deliberately kept separate from Core",
        "Two pointers in one paragraph: the 33rd record, and a requirements document.",
    ),
    Rewrite(
        "demo/transferunits/CONTEXT.md",
        "Its decisions are **ADR 0029, ADR 0030 and ADR 0032**. They live in the ADR directory of the Core\n"
        "Middleware context, in one shared sequence: `../../src/kapps_semantic_middleware/docs/adr/`. The root\n"
        "`CONTEXT-MAP.md` records which context each ADR governs.",
        "Its decisions are **ADR 0029, ADR 0030 and ADR 0032**. Those records are\n"
        "development-repository material and do not ship; what they decided is described, without\n"
        f"the deliberation, in `{_MECHANICS}`.",
        "The sixth glossary. #129's inventory missed it -- it names the directory, not a file.",
    ),
    # -- the two front doors --------------------------------------------------------------------
    Rewrite(
        "README.md",
        "| [`CONTEXT-MAP.md`](CONTEXT-MAP.md) | **Start here.** The five contexts, and which ADR governs which. |\n"
        "| `src/kapps_semantic_middleware/` | The library. |\n"
        "| `src/kapps_semantic_middleware/docs/adr/` | Core Middleware and TransferUnit Factory decision records. |\n"
        "| `docs/adr/` | Root records — decisions above every context, including the sibling dependency policy. |\n"
        "| `demo/transferunits/` | The factory demo: N units, a controller, one launcher command. |\n"
        "| `examples/` | Scenario 1 (operation coordination) and scenario 2 (direct state). |\n"
        "| [`docs/agents/`](docs/agents/) | Issue tracker, triage labels, and domain conventions for agents. |",
        "| [`CONTEXT-MAP.md`](CONTEXT-MAP.md) | **Start here.** The five contexts and how they relate. |\n"
        "| `src/kapps_semantic_middleware/` | The library. |\n"
        "| [`AGENTS.md`](AGENTS.md) | Consumption rules and the mechanics index, for an agent building against this. |\n"
        f"| [`{_MECHANICS}`]({_MECHANICS}) | How each mechanic is used, one page each. |\n"
        "| `demo/transferunits/` | The factory demo: N units, a controller, one launcher command. |\n"
        "| `examples/` | Scenario 1 (operation coordination) and scenario 2 (direct state). |",
        "Three of the seven rows point at directories that never ship. #129's inventory missed "
        "this file entirely, and it is the first thing a stranger reads.",
    ),
    Rewrite(
        "README.md",
        "**Read [SIBLINGS.md](SIBLINGS.md) first.** This project depends on three sibling repositories as\n"
        "editable path checkouts, all three are on unmerged feature branches, and `uv.lock` records none of\n"
        "that. A `main` checkout of any sibling fails, each in its own way.\n"
        "\n"
        "**You need KIT GitLab access to build this today.** One sibling, `aas_middleware_inf`, lives on a\n"
        "private KIT GitLab instance and has no public mirror. Without an account there, `uv sync` cannot\n"
        "resolve it, and no amount of local setup works around that.\n"
        "\n"
        "```bash\n"
        "python scripts/check_siblings.py   # verify the three siblings\n"
        "uv sync\n"
        'pytest -m "not live"               # the tier that needs no GraphDB\n'
        "```",
        "Everything this project needs resolves from PyPI.\n"
        "\n"
        "```bash\n"
        "pip install kapps-semantic-middleware\n"
        "```\n"
        "\n"
        "To also get the scenario notebooks and the TransferUnit factory demo:\n"
        "\n"
        "```bash\n"
        'pip install "kapps-semantic-middleware[demonstrations]"\n'
        "```\n"
        "\n"
        "Working from a checkout instead? `uv sync` installs the same set, and\n"
        '`pytest -m "not live"` runs the tier that needs no GraphDB.',
        "The whole setup section described the dev world: three siblings as editable path "
        "checkouts on unmerged branches, and -- worst -- 'You need KIT GitLab access to build "
        "this today'. In the public release that is not merely stale, it is the opposite of "
        "what the release means, and it points at two files that never ship (SIBLINGS.md, "
        "scripts/check_siblings.py). The released README has to describe the END state, "
        "because by then every dependency is on PyPI; leaving it would cost a second release "
        "to say so. Raised by Etienne, 2026-08-12.",
    ),
    Rewrite(
        "AGENTS.md",
        "The `CONTEXT.md` files cite architecture decision records as **ADR 00nn** and **root ADR 000n**, and\n"
        "in five places quote a full `docs/adr/....md` or `docs/prd/....md` path. Those records are\n"
        "development-repository material and are **not part of this distribution** — the paths do not\n"
        "resolve here, and no copy of them ships.",
        "The `CONTEXT.md` files cite architecture decision records as **ADR 00nn** and **root ADR\n"
        "000n**. Those records are development-repository material and are **not part of this\n"
        "distribution** — no copy of them ships, and the release rewrites every path that pointed\n"
        "at one, so a citation here is never a link you can follow.",
        "The note written to close this trap quoted the path form to name it, so it tripped "
        "check 5 itself. Its 'in five places' was also the undercount #129 inherited: the real "
        "figure is 14 occurrences across 8 shipped files.",
    ),
    Rewrite(
        "CONTEXT-MAP.md",
        "- [Module Requirements](./docs/prd/) — requirements this project places on sibling KAPPS-family\n"
        "  modules (`kapps_ogm`, the not-yet-created visual-toolbox GUI). Not a code context: a collection\n"
        "  of PRD documents, not a glossary + ADRs.",
        "- **Module Requirements** — requirements this project places on sibling KAPPS-family\n"
        "  modules (`kapps_ogm`, the not-yet-created visual-toolbox GUI). Not a code context, and its\n"
        "  documents are development-repository material that does not ship.",
        "A whole context whose body is an excluded directory. Kept as an entry rather than "
        "deleted, so 'five contexts' stays true in the four other files that say it.",
    ),
    # -- a source file, not a document ----------------------------------------------------------
    Rewrite(
        "src/kapps_semantic_middleware/shacl_interop/shape_from_typehints.py",
        "This is temporary scaffolding for workflow signature representation. See\n"
        "docs/adr/0001-shacl-for-workflow-signatures.md for context. This logic properly\n"
        "belongs in kapps_ogm. See docs/prd/kapps-ogm-shacl-support.md at the repo root.\n"
        "Delete this logic from here once that support lands.",
        "This is temporary scaffolding for workflow signature representation. This logic\n"
        "properly belongs in kapps_ogm. Delete this logic from here once that support\n"
        "lands.",
        "A module docstring, not a glossary. #129 assumed the pointers were all in documents.",
    ),
    # -- the stub -------------------------------------------------------------------------------
    Rewrite(
        "CLAUDE.md",
        "See [AGENTS.md](AGENTS.md). Working *on* this repo rather than against it? "
        "[`docs/agents/`](docs/agents/README.md).",
        "See [AGENTS.md](AGENTS.md).",
        "The second half links into docs/agents/, which never ships. No check catches a dead "
        "link to an excluded directory that is not a record directory -- only this rewrite does.",
    ),
)

SECTION_DROPS: tuple[SectionDrop, ...] = (
    SectionDrop(
        "CONTEXT-MAP.md",
        "## Where the ADRs live, and which context each one governs",
        "## Where the decisions are written down\n"
        "\n"
        "The architecture decision records are development-repository material and are not part of\n"
        "this distribution. What they decided is described, without the deliberation, in\n"
        f"[`{_MECHANICS}`]({_MECHANICS}); [`AGENTS.md`](AGENTS.md) indexes those pages.\n",
        "~60 lines describing two directories and 39 records, none of which reach the release "
        "tree. Dropped as a section rather than patched line by line.",
    ),
)


class RewriteError(RuntimeError):
    """A declared edit did not match its target exactly once."""


def apply_section_drop(text: str, drop: SectionDrop) -> str:
    """Replace ``drop.heading`` and its body, up to the next heading of equal or shallower rank.

    **Equal or shallower**, not equal alone. Matching only an exactly-equal rank skips deeper
    headings correctly and misses shallower ones entirely, so a `##` section followed by a `#`
    one never finds its end: it runs to EOF and the replacement swallows the rest of the file,
    silently. It bites when a README and a docs copy sit one heading rank apart, which is the
    shape `aas_middleware_inf` has -- and where #118 found it (#158 brings the fix back).
    """
    start = text.find(drop.heading)
    if start == -1:
        raise RewriteError(
            f"{drop.path}: heading {drop.heading!r} not found. The document was reworded; "
            "update SECTION_DROPS."
        )
    rank = len(drop.heading) - len(drop.heading.lstrip("#"))
    after = start + len(drop.heading)
    end = len(text)
    for candidate in range(after, len(text)):
        if not text.startswith("\n#", candidate):
            continue
        hashes = len(text[candidate + 1 :]) - len(text[candidate + 1 :].lstrip("#"))
        # The trailing space matters: without it `#hashtag` at the start of a line reads as a
        # rank-1 heading and ends the section early.
        if hashes <= rank and text.startswith(" ", candidate + 1 + hashes):
            end = candidate + 1
            break
    return text[:start] + drop.replacement + text[end:]


def apply_rewrite(text: str, rewrite: Rewrite) -> str:
    """Apply one exact-match substitution, insisting it matches exactly once."""
    hits = text.count(rewrite.old)
    if hits != 1:
        raise RewriteError(
            f"{rewrite.path}: expected exactly 1 match, found {hits}. "
            f"The file was reworded; update REWRITES. Reason for the edit: {rewrite.why}"
        )
    return text.replace(rewrite.old, rewrite.new)


def apply_all(tree: Path) -> list[str]:
    """Apply every rewrite and section drop to ``tree``. Returns the paths changed, sorted.

    **Bytes in, bytes out, with the line ending carried across.** Three behaviours are possible
    here and only one of them is right (#158):

    - *Text mode.* Python's universal newlines hand the rewrite ``\\n``, so it matches -- and
      writing back emits ``\\n`` everywhere, silently converting a CRLF file in full. Invisible
      in the working tree, enormous in the diff, and the diff is the only review a release tree
      gets.
    - *Raw bytes.* Nothing is converted, but the rewrite tables in this module are written with
      ``\\n`` literals, so on a CRLF file every one of them matches zero times and the release
      stops with `RewriteError`. Loud rather than silent, which is this module's stated
      preference -- but it means a Windows checkout cannot cut a release at all, and #113 made
      Windows a first-class target.
    - *Normalise, edit, restore.* What happens below. The rewrites see the ``\\n`` they were
      written against, and the file keeps the endings it arrived with.
    """

    def read(path: Path) -> tuple[str, bool]:
        """Return the text with ``\\n`` endings, and whether the file used CRLF."""
        raw = path.read_bytes().decode("utf-8")
        return raw.replace("\r\n", "\n"), "\r\n" in raw

    def write(path: Path, text: str, crlf: bool) -> None:
        """Write ``text`` back, restoring CRLF if that is what the file had."""
        if crlf:
            text = text.replace("\n", "\r\n")
        path.write_bytes(text.encode("utf-8"))

    changed: set[str] = set()

    for rewrite in REWRITES:
        target = tree / rewrite.path
        if not target.exists():
            raise RewriteError(f"{rewrite.path}: declared in REWRITES but missing from the tree.")
        text, crlf = read(target)
        write(target, apply_rewrite(text, rewrite), crlf)
        changed.add(rewrite.path)

    for drop in SECTION_DROPS:
        target = tree / drop.path
        if not target.exists():
            raise RewriteError(f"{drop.path}: declared in SECTION_DROPS but missing from the tree.")
        text, crlf = read(target)
        write(target, apply_section_drop(text, drop), crlf)
        changed.add(drop.path)

    return sorted(changed)


def edit_pyproject(text: str) -> str:
    """Cut the sibling path sources from the manifest.

    ``[tool.uv.sources]`` resolves the three siblings as editable checkouts next to this one, and
    ``[tool.uv]``'s override exists only to reconcile a dev-only git pin with them. Neither is
    true for anyone who installs from PyPI, and PyPI rejects a path dependency outright.

    Everything else is left alone -- in particular the wheel target's ``force-include``, which
    #130 put in the dev manifest precisely so that the wheel the cross-check builds is the wheel
    that ships.
    """
    drop_headers = ("[tool.uv.sources]", "[tool.uv]")
    kept: list[str] = []
    dropping = False

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped in drop_headers:
            dropping = True
            # Trailing blank lines and the comment block above the header belong to it.
            while kept and kept[-1].strip().startswith("#"):
                kept.pop()
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        if dropping:
            if stripped.startswith("[") and stripped.endswith("]"):
                dropping = False
            else:
                continue
        kept.append(line)

    return "".join(kept).rstrip() + "\n"
