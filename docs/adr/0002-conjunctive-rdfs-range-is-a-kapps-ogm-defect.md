# Multiple `rdfs:range` assertions are conjunctive, so `kapps_ogm` raising on them is a defect

> **MOTIVATION RESTORED AND CHANGED 2026-07-28 (#52). Now load-bearing again, on a different basis.**
>
> The 2026-07-27 retirement below stands as a record of what was believed then. Its *measurement*
> is still correct: RDFS does not entail a `rdfs:range` triple for a subproperty, and GraphDB
> materializes none. What changed is that we no longer need it to. ADR 0026 has the OGM **walk
> `rdfs:subPropertyOf*` itself** and merge the anonymous restriction ranges it finds. This is the
> entailment the reasoner does not materialize (rdfs7 then rdfs3: the value node is an instance of
> every range class along the chain, hence of their intersection). Range-on-superproperty therefore
> *does* work as a mechanism. It works not by inheritance, but by explicit resolution.
>
> So the second bullet's conclusion ("range-on-superproperty does not work as a mechanism here") is
> superseded. It is true of the reasoner and false of the OGM we ask for. The first bullet is
> also superseded. We extend upstream properties again, though from the interface side rather than
> by addition of ranges to `tu:` properties. We do this per instance rather than in the TBox.
>
> `SAWeindel/kapps_ogm#1` is now one requirement (R7) of
> `docs/prd/kapps-ogm-anonymous-node-identity.md`, not an independent fix, and it gates scenario 3's
> provisioning flow. See also root ADR 0003 for why the surrounding work is specified rather than
> patched.

> **MOTIVATION RETIRED 2026-07-27 (#25). Still correct. No longer urgent, and no longer gating.**
>
> Both driving use cases below have gone away. One rested on a factual error:
>
> - *"Upstream properties cannot be extended."* We no longer want to extend them. Connection metadata
>   does not belong in a range restriction at all. The domain TBox and the connector's `inf:` TBox are
>   deliberately unconnected. The middleware joins the two at runtime. `tu:hasConveyorSpeed`
>   keeps exactly the restriction upstream gives it.
> - *"The interface hierarchy cannot carry ranges, because subproperties would inherit two."* **Wrong.**
>   RDFS does not entail a `rdfs:range` triple for a subproperty. Neither GraphDB repository
>   materializes one. Measured, `include_implicit=True` returns **0** inherited ranges on both. A
>   property with its own range plus a superproperty range resolves to exactly **1**. There was never a
>   collision to avoid. (It also means range-on-superproperty does not *work* as a mechanism here: the
>   subproperty resolves to no range at all and `PropertySpec.specify` raises "no rdfs:range defined".)
>
> The RDFS reading is still right and the raise is still a defect. `SAWeindel/kapps_ogm#1` stays
> open as a correctness fix. But it **no longer gates #39**, and nothing in scenario 3 waits on it.

`PropertySpec.specify` raises `ValueError: Property ... has multiple rdfs:range defined` whenever a
property resolves to more than one range. RDFS semantics are **conjunctive**. Several `rdfs:range`
assertions mean a value must satisfy *all* of them. This is their intersection. The correct
behavior is to intersect the restrictions into one nested `ClassSpec`, not to refuse. This is a
correctness bug. Under root ADR 0001 it is therefore fixed in the `kapps_ogm` checkout, with a
detailed changelog entry, rather than worked around here.

The fix is a judgement call about RDFS semantics, and it touches the OGM's central specification
path. It therefore gets its own grilling session in the `kapps_ogm` repository before implementation.

## Why

### It is the wall in front of the consolidation

A parameter's materialized shape is exactly its property's `rdfs:range` restriction (#29). Two
consequences follow. The raise blocks both:

- **Upstream properties cannot be extended.** `tu:hasConveyorSpeed`'s restriction declares
  `inf:hasValue` and `tu:hasUnit`. It declares no topic and no broker. The `tu:` TransferUnit ontology is fixed and
  authoritative. We reuse it rather than paraphrase it. Assertion of an additional range from our own
  file is the natural additive move. The raise forbids precisely this.
- **The interface hierarchy cannot carry ranges.** `tu:hasConveyorSpeed` is already
  `rdfs:subPropertyOf inf:isInterfaceAccessibleMQTTParameter`. Give that superproperty a range. This is
  the obvious place to say what metadata every MQTT parameter carries. It would make every subproperty
  resolve two ranges by inheritance. This turns a working fetch into a crash. The superproperties have
  no range today. This is the only reason the current code works at all.

Without the fix, the consolidation's options collapse to minting parallel `tux:` properties that
paraphrase the upstream vocabulary. We decided not to do this.

### It is a bug, not a feature request

The distinction matters because root ADR 0001 permits only bugfixes in siblings. The raise is not a
deliberate restriction with a rationale to be weighed. It is an incorrect reading of RDFS. It treats
a legal, meaningful ontology as malformed. Fix it makes `kapps_ogm` agree with the specification
it implements. The rejected alternatives are mint parallel subproperties in our own namespace, or keep
connection metadata out of the graph entirely and configure connectors in Python. Both work around
correct ontologies that the OGM mishandles. The second would gut ADR 0023's premise. A
domain expert can register a resource by authorship of instance data.

## Consequences

- `kapps_ogm` gains intersection semantics for multiple ranges: restriction members are merged. A
  genuine conflict (the same property constrained to incompatible types) becomes the error case
  that the arity check stands in for today.
- Our extended `transferunit.ttl` (#25) may **add** a range restriction to an upstream property.
  This lets scenario3 carry MQTT metadata on authoritative `tu:` properties.
- The consolidation (#39) may put connection-metadata declarations on the `inf:` interface
  superproperties. Domain properties inherit them.
- A detailed changelog entry in `kapps_ogm` is required, per root ADR 0001.
- Sequencing: the grilling session and fix land in `kapps_ogm` before #39 is authored. Its
  shape depends on the existence of the fix.

Raised by wayfinder ticket #29 under map #24.
