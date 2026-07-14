# PRD: Visual toolbox for guided ontology-class authoring

**Origin**: raised during design of
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`
(`kapps_semantic_middleware`), which commits
to "ontology as ground truth" — every Capability, Workflow, Service, and StateProperty type a
`@workflow`/`@state` registration references must be pre-authored in the ontology before the
middleware using it can start.
**Status**: requirement capture only. No repository exists yet; this document is the seed for
one, not a spec for existing code.
**Audience**: whoever scopes and builds this tool.

## Problem

The organization building on KAPPS has roughly twenty domain engineers, each developing their
own resource integrations (doors, transformer cells, sensors, conveyor modules — one per
physical device type or family), against a single ontology engineer. The ontology-as-ground-
truth ADR referenced above means every
one of those twenty engineers' `@workflow`/`@state` registrations depends on a
Capability/Workflow/Service class and a SHACL shape existing in the ontology *before* their
code can run at all — authored correctly (right superclass, right SHACL property paths and
datatypes matching their function's actual signature) by, or with the involvement of, the one
ontology engineer. At twenty-to-one, that person becomes the bottleneck for every new
integration, and the failure mode when a domain engineer tries to author Turtle/SHACL
themselves without deep semantic-web background is exactly the kind of subtly-wrong ontology
(wrong domain/range, missing inverse property, cardinality that doesn't match reality) that is
expensive to catch later, once instance data has accumulated against it.

## Goal

A graphical tool that walks a domain engineer through the decisions needed to define a new
Capability/Workflow/Service/StateProperty type — without requiring them to write Turtle, know
OWL/SHACL syntax, or understand the full Core ontology — while producing output the ontology
engineer can review and merge with confidence, rather than reverse-engineer.

## Requirements (draft, to be sharpened by whoever scopes this properly)

- **R1 — Guided class creation for the four registration-relevant types.** Given "I'm building
  a new Workflow for my resource, called X, that takes these arguments and returns this," the
  tool produces a correctly-shaped `owl:Class` (subclassing the right `svc:` base class) plus
  its `sh:NodeShape` (per the pattern in
  `src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`)
  — without the domain engineer writing RDF by hand.
- **R2 — Reuse existing Capability/Resource types where they already fit.** Before letting
  someone create a new Capability type, the tool should surface existing ones that might
  already cover the same real-world ability (avoiding e.g. `DoorOpenCapability` and
  `HatchOpenCapability` proliferating as near-duplicates because two engineers didn't know
  about each other's work).
- **R3 — Validation before submission, not after merge.** Whatever the tool produces should be
  checked for basic well-formedness (valid IRIs, consistent prefixes, SHACL shapes that
  actually parse) before it ever reaches the ontology engineer, so their review time goes to
  *domain* correctness, not syntax errors.
- **R4 — A review/merge step the ontology engineer stays in control of.** This tool lowers the
  effort of *producing* a correct proposal; it does not remove the ontology engineer from the
  loop entirely — final authority over what enters the shared ontology (naming consistency,
  avoiding redundant concepts, deciding what's genuinely core vs. domain-specific) stays
  human, at least until there's enough track record to reconsider that.
- **R5 — Output compatible with the Git-based ontology engineering pipeline.** The paper's
  Ontology Layer already describes Git-based version control with CI/CD validation for
  ontology modules (§4.1). Whatever this tool produces should slot into that pipeline (e.g. as
  a branch/PR) rather than write directly into a running triple store, so it benefits from
  the same review and validation gates as hand-authored ontology changes.

## Non-goals

- Replacing the ontology engineer's judgment on cross-cutting/core concepts — this tool is
  scoped to the repeatable, mechanical part of authoring domain-specific Capability/Workflow/
  Service/StateProperty classes, not general-purpose ontology engineering.
- Anything related to instance data — this is purely a class/shape-authoring tool.
