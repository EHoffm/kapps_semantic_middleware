# Scenario parts live in the demo, and the core grows only generic features

The library under `src/kapps_semantic_middleware/` holds generic functions only. Every part of a
scenario lives under `demo/`. No scenario code enters the library.

The monitor, the controller and the TransferUnit resource logic are parts of scenario 3. All three
belong in `demo/`.

**The rule for a doubtful case.** Write the function in the demo. Write it again for each part of the
demo that needs it. Duplication is correct at this stage.

**The promotion rule.** After the scenario 3 demo runs, review the duplicates. Move a function into
the library only after a decision that the middleware needs it for every task.

## Why

### A demo that runs teaches better than a guess

Etienne set this rule on 2026-08-01. The team returns to the demo after it runs, and the team learns
from it. A feature enters the source code only after a decision that the middleware needs it *"for all
its possible tasks"*.

A function promoted early carries the shape of the one scenario that produced it. The library then
owns an interface that no second consumer asked for. A third duplicate in the demo shows which parts
are truly common, and which parts only looked common.

### Duplication is cheap here, and a wrong core interface is not

Three copies of a discovery query cost three edits. A generic function in the library costs a public
interface, a test suite, and a migration for every consumer when the shape turns out wrong. The demo
is the cheap place to be wrong.

### The boundary must be visible, not judged case by case

A rule that asks "is this generic enough" produces a different answer from each author. A rule that
says "demo first, always" produces one answer. The review after the demo runs is where judgment
belongs, and one person makes every promotion decision at that point.

## Consequences

- ~~`src/kapps_semantic_middleware/controller.py` is misplaced today.~~ **Done.** It held 473 lines
  of scenario 3 discovery code from commit `1fead76`, and it moved to `demo/transferunits/`, where
  it is now `demo/transferunits/controller.py`. No `controller.py` remains in the library.
- The monitor duplicates the controller's discovery code rather than shares a base class (ADR 0032).
- `seeding.py` stays in the library. `clear_repository` and `load_shared_ontologies` are generic, and
  ADR 0030 already keeps the unit shape out of them.
- `activity.py` stays in the library. The feed is mode-agnostic and carries no scenario knowledge.
- A new module in `src/` needs a stated reason. The reason names the second consumer that needs it.

This decision comes from wayfinder ticket #59, under map #57.

## Amendment, 2026-08-03, ticket #33 — what "extraction waits" governs

This ADR says scenario parts live in `demo/`, the core grows only generic features, and **extraction
waits until the demo runs**. Ticket #33 produced the first case where those clauses point in opposite
directions, so the boundary between them is now stated rather than inferred.

**The rule.** *"Extraction waits"* governs code that **carries domain knowledge** — code written
against one scenario, whose generic shape can only be known once the scenario runs. A **protocol
mechanism the middleware itself defines** carries no domain knowledge at any point in its life. It is
generic at birth, there is nothing scenario-specific to strip out later, and it enters `src/`
directly.

**The case that forced it.** ADR 0033's REST connector speaks the ADR 0017 route structure — a
protocol this middleware defines — and names no domain term. Waiting for the demo to run would teach
it nothing it does not already know. Two further facts settled it: `connectors/mqtt_binding.py`, its
exact sibling, is already in the library, and the recognition rule it depends on is a change to
`connectors/semantic.py`, which is in the library regardless. Splitting a recognition rule from the
class it recognises is worse than either placement.

**What this does not license.** The controller, the monitor and the mock PLC stay in `demo/`. They
carry domain knowledge, and the original rule governs them unchanged. A new module in `src/` still
needs a stated reason, and "it is a protocol mechanism" is now one of the reasons it may state.

## Amendment, 2026-08-12, ticket #146 — `credentials.py`, and the demo literal it carries

This ADR requires that *"a new module in `src/` needs a stated reason. The reason names the second
consumer that needs it."* `src/kapps_semantic_middleware/credentials.py` is such a module. This is
its stated reason, and an honest note about the one part of it that sits awkwardly here.

**The module.** It builds a GraphDB client from `GRAPHDB_URL` / `GRAPHDB_USERNAME` /
`GRAPHDB_PASSWORD` with the repository supplied by the caller, so that a `GRAPHDB_REPOSITORY` left in
someone's environment cannot name the repository that the test suite or the demo then wipes.

**The second consumer is real, and there are three.** `demo/transferunits/` (four call sites),
`examples/` (three), and `tests/` (one, plus seventeen more building a second client). The rule for a
doubtful case above — write it in the demo, write it again for each part that needs it — would put the same
credential-construction logic in three trees, one of which ships to users and one of which does not
ship at all. Duplication is cheap when the copies are three discovery queries. It is not cheap when
each copy is a place that can forget to override, and forgetting means clearing a repository nobody
asked to clear.

**The 2026-08-03 amendment's test applies.** `credentials_for` carries no domain knowledge: it names
no TransferUnit, no belt, no capability, and running the scenario would teach it nothing it does not
already know. It is generic at birth, in the sense that amendment established.

**Where it sits awkwardly, stated rather than hidden.** The module also exports
`DEMO_REPOSITORY = "kapps-demo"`. That constant *is* scenario-adjacent — it is the name
`docker/docker-compose.yml` creates — and by the letter of this ADR it belongs under `demo/`. It is
here because `examples/` needs it too, and `examples/` is not `demo/`; putting the literal in one and
importing it into the other couples two trees that are deliberately independent, while writing it in
both is precisely the drift a repository name must not suffer. A test reads the name back out of
`docker/graphdb-repo-config.ttl`, so the two cannot separate silently.

**This placement is provisional, and the cleanup is a decision already taken.** The whole mechanism
is a stopgap for v0.1.0. It stops a stray variable reaching a real repository; it does not give a run
a clean slate or leave no trace, because clearing still happens at the start of a run rather than the
end. The full requirement needs a disposable repository created and dropped around each run — which
`graph_db_interface` cannot express, having no repository lifecycle, and which would need
`ROLE_ADMIN` if bolted on here.

Ticket #149 moves that lifecycle onto the triplestore interface, where it belongs, and is blocked on
#133 creating that repository. **When #149 lands, `credentials.py` should shrink or disappear**: the
disposable-repository context manager replaces `graphdb_for`, and `DEMO_REPOSITORY` goes back to
`demo/` where this ADR says it belongs, because a disposable repository has no shipped name to share.
Reviewers should treat the module as scaffolding with a scheduled removal, not as a new permanent
seam in the library.
