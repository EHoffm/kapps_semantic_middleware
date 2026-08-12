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
aas-middleware     = { path = "../aas_middleware_inf", editable = true }
kapps-ogm          = { path = "../kapps_ogm",          editable = true }
graph-db-interface = { path = "../graph_db_interface", editable = true }
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
| `graph_db_interface` 2.0.1 | `mint_service_iri` rejects a `host:port` form; and `GraphDB` has no `close()`, so every live test session ends in `AttributeError` at fixture teardown — `close` arrived with `c90c940`, which is on `dev_semantic_middleware` and not on `main` |
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
git clone https://github.com/SAWeindel/kapps_ogm.git
git clone https://github.com/JaFeKl/graph_db_interface.git
git clone git@gitlab.kit.edu:kit/ifl/opensource/circular_factory/inf/semantic_middleware_dev/aas_middleware_inf.git

# 2. graph_db_interface's branch is on the SAWeindel FORK, not on origin.
#    Cloning origin alone will not find it.
git -C graph_db_interface remote add saweindel https://github.com/SAWeindel/graph_db_interface.git
git -C graph_db_interface fetch saweindel

# 3. Check out the pinned branch in each sibling. All three carry the same name.
git -C graph_db_interface checkout dev_semantic_middleware
git -C kapps_ogm          checkout dev_semantic_middleware
git -C aas_middleware_inf checkout dev_semantic_middleware

# 4. Verify before building anything.
cd kapps_semantic_middleware
python scripts/check_siblings.py
uv sync
```

The exact commits, and the reason for each, are in
[`siblings.lock.toml`](siblings.lock.toml). `check_siblings.py` reads that file — it is the single
source of truth, and this document only explains it.

## `aas_middleware_inf` is private

It lives on KIT's GitLab and has no public mirror. Without access to it the project cannot be built
at all, because the two sync-layer fixes it carries (#92 and #94) are not in any released
`aas-middleware`. There is no workaround. It also carries the manifest fix for #103, which changes
no behaviour.

## When a sibling moves

Anyone who advances a sibling on purpose updates `siblings.lock.toml` in the same change, with the
new commit and a sentence on why it is needed. `check_siblings.py` then fails for everyone else
until they catch up, which is the intent — a silent divergence is what produced the situation this
file documents.

It also fails on **unpushed** commits and on a **dirty** working tree. A commit that exists only on
one machine reproduces nowhere, so from every other machine's point of view it does not exist.

## The environment

Separately from the siblings, the integration tests and the demo need a reachable GraphDB:

```bash
GRAPHDB_URL=...  GRAPHDB_USERNAME=...  GRAPHDB_PASSWORD=...  GRAPHDB_REPOSITORY=...
```

Tests that need it are marked `live` automatically and skip when those are unset, so
`pytest -m "not live"` runs anywhere.
