# Setting up a machine: the three sibling repositories

**If something fails in a way the code does not explain, run this first:**

```bash
python scripts/check_siblings.py
```

## Why this file exists

`kapps_semantic_middleware` depends on three sibling repositories, wired as **editable path
dependencies** under root ADR 0001:

```toml
[tool.uv.sources]
aas-middleware              = { path = "../aas_middleware_inf",            editable = true }
kapps-ogm                   = { path = "../kapps_ogm",                     editable = true }
kapps-triplestore-interface = { path = "../kapps_triplestore_interface",   editable = true }
```

That is a deliberate choice — it lets a defect be fixed where it lives instead of worked around
here — but it has a cost that was not written down until now:

**`uv.lock` pins nothing about a sibling's contents.** It records
`source = { editable = "../aas_middleware_inf" }`. A path. No revision, no branch, no commit. The
version floors in `pyproject.toml` (`aas-middleware>=0.2.6`) are equally weak: they are satisfied by
any commit that still calls itself 0.2.6.

So each machine imports whatever its local sibling checkout happens to be sitting on, and **each
wrong commit produces a different failure**:

| sibling on `main` | how it fails |
|---|---|
| `kapps_triplestore_interface` on the pre-fork tree | `mint_service_iri` rejects a `host:port` form; and `GraphDB` has no `close()`, so every live test session ends in `AttributeError` at fixture teardown — `close` arrived with `c90c940`, which is on `dev_semantic_middleware` and not on `main` |
| `kapps_ogm` 0.1.2 | the seed step fails on the `isOccupied` range |
| `aas_middleware_inf` | northbound sync goes deaf; ramping belts freeze short of their setpoint |

**All three siblings are on unmerged branches.** A checkout of `main` in any of them does
not reproduce a working demo, and never has. `siblings.lock.toml` is the record of what does.

**Since 2026-08-09 all three carry the same branch name: `dev_semantic_middleware`.** Its head in
each repository is exactly the commit this project is known to run against, so setup is one
command repeated three times rather than three feature-branch names to look up. Every one of them
is pushed, so a second machine can obtain them — which was not true before: `kapps_ogm` was on a
local-only branch, and `aas_middleware_inf` had uncommitted changes nobody else could see.

The feature branches those commits came from still exist and are untouched. This is a stable
name in front of them, not a replacement for them.

## Setting up

```bash
# 1. All four repositories side by side in one parent directory.
git clone https://github.com/EHoffm/kapps_semantic_middleware.git
git clone git@gitlab.kit.edu:kit/ifl/opensource/circular_factory/inf/semantic_middleware_dev/kapps_ogm.git
git clone git@gitlab.kit.edu:kit/ifl/opensource/circular_factory/inf/semantic_middleware_dev/kapps_triplestore_interface.git
git clone git@gitlab.kit.edu:kit/ifl/opensource/circular_factory/inf/semantic_middleware_dev/aas_middleware_inf.git

# 2. Check out the pinned branch in each sibling. All three carry the same name.
git -C kapps_triplestore_interface checkout dev_semantic_middleware
git -C kapps_ogm                   checkout dev_semantic_middleware
git -C aas_middleware_inf          checkout dev_semantic_middleware

# 3. Verify before building anything.
cd kapps_semantic_middleware
python scripts/check_siblings.py
uv sync
```

The exact commits, and the reason for each, are in
[`siblings.lock.toml`](siblings.lock.toml). `check_siblings.py` reads that file — it is the single
source of truth, and this document only explains it.

## All three are private

**Since #119, and it took three tickets to get here.** All three siblings now live on KIT's
GitLab and none has a public mirror. Without access to them the project cannot be built at all:
the two sync-layer fixes `aas_middleware_inf` carries (#92 and #94) are in no released
`aas-middleware`, and there is no workaround. It also carries the manifest fix for #103, which
changes no behaviour.

`kapps_triplestore_interface` arrived second, and is the reason the step that used to say *"its
branch is on the SAWeindel FORK, not on origin"* is gone. #133 forked `JaFeKl/graph_db_interface`,
renamed it, and gave it a home of its own -- so the branch and the repository finally agree, and
there is one remote to add instead of two.

`kapps_ogm` arrived last, in #119, and it is the only one that **moved** rather than being
created. It was at `github.com/SAWeindel/kapps_ogm`, public, carrying 18 agent-coauthored
commits. That repository still exists; it is not the one this project builds against, and a
clone of it will not satisfy `check_siblings.py`.

Their public counterparts on PyPI -- `kapps-triplestore-interface` and `kapps-ogm` -- are
**publish targets and not mirrors**: each receives one commit per release, so neither is
somewhere to clone from and develop against.

> The GitLab group `semantic_middleware_dev` is expected to be renamed to `KAPPS_Dev`. When that
> happens, both URLs above and both in `siblings.lock.toml` move together.

## When a sibling moves

Anyone who advances a sibling on purpose updates `siblings.lock.toml` in the same change, with the
new commit and a sentence on why it is needed. `check_siblings.py` then fails for everyone else
until they catch up, which is the intent — a silent divergence is what produced the situation this
file documents.

It also fails on **unpushed** commits and on a **dirty** working tree. A commit that exists only on
one machine reproduces nowhere, so from every other machine's point of view it does not exist.

**When that does not happen, the check says so instead of misdirecting you.** A pin left behind its
own branch used to draw an unconditional *"fetch, then check the branch out"* — which lands on the
branch tip, not on the pin, so the check stayed red and now reported a different sha. The tool was
telling you to do something it would then reject. It now names both commits and says which of the
two is out of date, because when a branch has moved past its pin the answer is always to advance
the pin here, never to change the checkout (#152).

**A sibling's manifest change lands in `uv.lock`, and that change gets committed.** The path source
carries no revision, so every resolve re-reads the sibling's *current* metadata: change a dependency
there and the next `uv run` here rewrites `uv.lock` with a diff nobody typed. That diff is real —
the lock now describes what this project actually installs — so it belongs in the same commit as the
pin that caused it. Do not `git restore` it. `prepare_release.py` refuses to run against a modified
tracked file deliberately, and clearing that gate by hand before every release is how a gate stops
being believed.

The first instance was #103's `httpx = "^0.27.0"` in `aas_middleware_inf`: two lines under the
`aas-middleware 0.2.6` block, returning after every `git restore`. Both this and the pin drift above
expire with #120, which replaces the path sources with published version pins and deletes
`siblings.lock.toml` and `check_siblings.py` with them.

## The environment

Separately from the siblings, the integration tests and the demo need a reachable GraphDB:

```bash
GRAPHDB_URL=...  GRAPHDB_USERNAME=...  GRAPHDB_PASSWORD=...
```

Three, not four. The repository is named in code — `Tests` for the suite, `kapps-demo` for the demo
and the examples — and a `GRAPHDB_REPOSITORY` in your environment is ignored rather than obeyed,
because these are the parts that wipe whatever they connect to (#146).

Tests that need it are marked `live` automatically and skip when those are unset, so
`pytest -m "not live"` runs anywhere.
