# PRD: Visual toolbox for guided ontology-class authoring

**Origin**: raised during design of
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`
(`kapps_semantic_middleware`). This commits
to "ontology as ground truth". The ontology must pre-author every Capability, Workflow, Service,
and StateProperty type that a `@workflow`/`@state` registration references, before the middleware
using it can start. An ontology engineer must author it.
**Status**: requirement capture only. No repository exists yet. This document is the seed for
one. Not a spec for existing code.
**Audience**: whoever scopes and builds this tool.

## Problem

The organization building on KAPPS has roughly twenty domain engineers. Each develops their
own resource integrations (doors, transformer cells, sensors, conveyor modules — one per
physical device type or family). One ontology engineer supports them. The ontology-as-ground-truth
ADR referenced above means each of those twenty engineers' `@workflow`/`@state` registrations
depends on one thing. A Capability/Workflow/Service class and a SHACL shape must exist in the
ontology before their code can run at all. An ontology engineer must author it correctly (right superclass, right SHACL property paths and
datatypes matching their function's actual signature). Or involve the one
ontology engineer. At twenty-to-one, that person becomes the bottleneck for every new
integration. The failure mode exists when a domain engineer tries to author Turtle/SHACL
themselves without deep semantic-web background. It is exactly the kind of subtly-wrong ontology
(wrong domain/range, missing inverse property, cardinality that does not match reality). Catch it later is
expensive. Instance data accumulates against it by then.

## Goal

A graphical tool walks a domain engineer through the decisions needed to define a new
Capability/Workflow/Service/StateProperty type. They do not need to write Turtle. They do not need to know
OWL/SHACL syntax. They do not need to understand the full Core ontology. The tool produces output the ontology
engineer can review and merge with confidence. They do not need to reverse-engineer it.

## Requirements (draft, to be sharpened by whoever scopes this properly)

- **R1 — Guided class creation for the four registration-relevant types.** Take an example. A
  domain engineer says: "I need a new Workflow for my resource, called X. It takes these
  arguments and returns this." The tool responds. It produces a correctly-shaped `owl:Class`
  that subclasses the right `svc:` base class. It also produces the matching `sh:NodeShape`
  (per the pattern in
  `src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`).
  The domain engineer does not write RDF by hand.
- **R2 — Reuse existing Capability/Resource types where they already fit.** Before a domain
  engineer creates a new Capability type, the tool should surface existing ones. These might
  already cover the same real-world ability. Avoid proliferation of near-duplicates (e.g. `DoorOpenCapability` and
  `HatchOpenCapability`). Two engineers did not know about each other's work.
- **R3 — Validation before submission, not after merge.** Whatever the tool produces should be
  checked for basic well-formedness (valid IRIs, consistent prefixes, SHACL shapes that
  actually parse) before it ever reaches the ontology engineer. Their review time goes to
  *domain* correctness, not syntax errors.
- **R4 — A review/merge step the ontology engineer stays in control of.** This tool lowers the
  effort of *production* of a correct proposal. It does not remove the ontology engineer from the
  loop entirely. Final authority over what enters the shared ontology (naming consistency,
  avoidance of redundant concepts, decision of what is genuinely core vs. domain-specific) stays
  human. Reconsider that only until enough track record exists.
- **R5 — Output compatible with the Git-based ontology pipeline.** The paper's
  Ontology Layer already describes Git-based version control with CI/CD validation for
  ontology modules (§4.1). Whatever this tool produces should slot into that pipeline (e.g. as
  a branch/PR). It does not write directly into a running triple store. It benefits from
  the same review and validation gates as hand-authored ontology changes.

## Non-goals

- Replacement of the ontology engineer's judgment on cross-cutting/core concepts. This tool is
  scoped to the repeatable, mechanical part of authoring domain-specific Capability/Workflow/
  Service/StateProperty classes. Not general-purpose ontology engineering.
- Anything related to instance data. This is purely a class/shape-authoring tool.
