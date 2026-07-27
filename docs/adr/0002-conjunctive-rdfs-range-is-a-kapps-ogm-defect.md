# Multiple `rdfs:range` assertions are conjunctive, so `kapps_ogm` raising on them is a defect

`PropertySpec.specify` raises `ValueError: Property ... has multiple rdfs:range defined` whenever a
property resolves to more than one range. RDFS semantics are **conjunctive** — several `rdfs:range`
assertions mean a value must satisfy *all* of them, i.e. their intersection — so the correct
behaviour is to intersect the restrictions into one nested `ClassSpec`, not to refuse. This is a
correctness bug, and under root ADR 0001 it is therefore fixed in the `kapps_ogm` checkout, with a
detailed changelog entry, rather than worked around here.

Because the fix is a judgement call about RDFS semantics and touches the OGM's central specification
path, it gets its own grilling session in the `kapps_ogm` repository before implementation.

## Why

### It is the wall in front of the consolidation

A parameter's materialized shape is exactly its property's `rdfs:range` restriction (#29). Two
consequences follow, and the raise blocks both:

- **Upstream properties cannot be extended.** `tu:hasConveyorSpeed`'s restriction declares
  `inf:hasValue` and `tu:hasUnit` — no topic, no broker. The `tu:` TransferUnit ontology is fixed and
  authoritative; we reuse it rather than paraphrase it. Asserting an additional range from our own
  file is the natural additive move, and it is precisely what the raise forbids.
- **The interface hierarchy cannot carry ranges.** `tu:hasConveyorSpeed` is already
  `rdfs:subPropertyOf inf:isInterfaceAccessibleMQTTParameter`. Giving that superproperty a range —
  the obvious place to say what metadata every MQTT parameter carries — would make every subproperty
  resolve two ranges by inheritance, turning a working fetch into a crash. The superproperties have
  no range today, which is the only reason the current code works at all.

Without the fix, the consolidation's options collapse to minting parallel `tux:` properties that
paraphrase the upstream vocabulary — the thing we decided not to do.

### It is a bug, not a feature request

The distinction matters because root ADR 0001 permits only bugfixes in siblings. The raise is not a
deliberate restriction with a rationale to be weighed; it is an incorrect reading of RDFS treating
a legal, meaningful ontology as malformed. Fixing it makes `kapps_ogm` agree with the specification
it implements. The rejected alternatives — mint parallel subproperties in our own namespace, or keep
connection metadata out of the graph entirely and configure connectors in Python — both work around
correct ontologies that the OGM mishandles, and the second would gut ADR 0016's premise that a
domain expert can register a resource by authoring instance data.

## Consequences

- `kapps_ogm` gains intersection semantics for multiple ranges: restriction members are merged, and
  a genuine conflict (the same property constrained to incompatible types) becomes the error case
  that the arity check is standing in for today.
- Our extended `transferunit.ttl` (#25) may **add** a range restriction to an upstream property,
  which is what lets scenario3 carry MQTT metadata on authoritative `tu:` properties.
- The consolidation (#39) may put connection-metadata declarations on the `inf:` interface
  superproperties and let domain properties inherit them.
- A detailed changelog entry in `kapps_ogm` is required, per root ADR 0001.
- Sequencing: the grilling session and fix land in `kapps_ogm` before #39 is authored, since #39's
  shape depends on the fix existing.

Raised by wayfinder ticket #29 under map #24.
