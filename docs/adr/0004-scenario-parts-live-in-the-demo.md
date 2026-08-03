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

- `src/kapps_semantic_middleware/controller.py` is misplaced today. It holds 473 lines of scenario 3
  discovery code, and it landed in commit `1fead76`. It moves to `demo/transferunits/`. Only
  `tests/test_controller_discovery.py` imports it, so the move touches two files. Tracked on #43.
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
