# The northbound projection prunes the ClassSpec, and the ontology decides what is pruned

The middleware builds its northbound view by **removing protocol metadata from the `ClassSpec` before fetching**. It passes the pruned spec to `OGM.fetch(class_spec=…)`. What counts as protocol metadata is read from the ontology. This happens per parameter, at every startup. It never comes from the set of connectors this middleware happens to have code for. The pruning runs **unconditionally**, for every flavour. This includes one that wires no connectors at all.

Walking upward from one parameter property:

| level | contributes | verdict |
|---|---|---|
| the parameter property's own range | value, unit | **keep** — domain content |
| protocol markers between it and `inf:isInterfaceAccessibleParameter` | broker, topics, endpoints | **delete** |
| `inf:isInterfaceAccessibleParameter`'s own range | `inf:accessMode` | **keep** — northbound-safe |

> **Consolidated 2026-07-29.** This ADR absorbs **ADR 0019** ("the northbound projection is middleware-side; a ClassScope cannot select within a parameter"), whose file is deleted. The projection question has now been decided four times. **How we got here preserves the route.** No future reader has to reconstruct it from four documents. This one had to from three.

## The mechanic that constrains every answer

*(established by ADR 0019, reproduced live under ticket #29, and still true)*

**A `ClassScope` selects which parameters a consumer sees. It cannot select within one.** Three mechanics in `kapps_ogm` combine to make a parameter node's contents fixed and identical for every consumer:

1. `OGM._fetch_complex_property` issues a bare `?bnode ?property ?value`. Every property of the node appears. No filter applies. No scope is consulted.
2. `PropertySpec.specify` routes a `COMPLEX` property to `_specify_complex_property`. It takes no `nested_scope` argument at all. A chain element below a complex property is dropped silently.
3. The node's shape therefore comes entirely from the property's `rdfs:range` restriction. This is the TBox.

ADR 0018's worked example scoped three levels deep to reach inside the parameter. It was silently discarded when run. That example was corrected in place.

So the projection cannot be expressed as a view "declining to fetch" the metadata. **Something has to act**, and the only question is what it acts on and how it decides.

## Why the ontology decides, and not the registry

The first implementation built the delete set from the **registry**. It used the union of every registered binding descriptor's `connection_metadata`. It attracted the team because the core then named no protocol term (ADR 0021). A domain expert's own connector was covered for free.

**It fails open, and that was measured.** A belt was made reachable over MQTT *and* OPC-UA, with no OPC-UA binding registered. The served payload:

```
hasValue         = []
hasUnit          = ['m/s']
accessMode       = ['readwrite']
hasOPCUAEndpoint = ['opc.tcp://10.0.0.5:4840/belt']     <- served
```

The MQTT metadata was removed. The OPC-UA endpoint was not. A set derived from registered code only knows the protocols someone wrote a connector for. Two protocols on one parameter is not a contrived case. **ADR 0026 names it explicitly.** It appears as own-built hardware whose protocol is not known when the ontology is authored. It also appears as two machines of one class on different protocols.

This is exactly the failure mode issue #42's *"do not add a deny-list of southbound field names"* was written to prevent. A registry-derived deny-list is still a deny-list. Deriving it from code rather than typing it by hand does not change what happens to the entries nobody thought of.

**The ontology does not have this blind spot.** It is authoritative about what a protocol parameter *is*. This holds whether or not anyone wrote a connector for it. Asking it finds the OPC-UA endpoint. Since everything reaching the productive graph goes through the OGM write path (root ADR 0008), what the ontology declares can be governed at admission. This is the other half of why trusting it is sound.

**Recomputed at every startup.** Consuming middlewares are decentralized. They live inside domain experts' own Python packages. The ontology may grow a protocol since a given instance last started. That instance must not serve a term it has never heard of.

## Why not a keep-list

Naming what is *safe* and dropping everything else is the fail-closed construction. It was the first remedy proposed. Rejected on two grounds, both structural:

- **It is a closed-world assertion in the serving path.** The architecture has exactly one closed-world moment by design. This is SHACL at admission (ADR 0025). A keep-list would add a second. It would appear in the place where open-world data is read back out.
- **It fights the domain ontologies' evolution.** Domain experts add terms. A keep-list hides every new legitimate one by default. Somebody must declare it safe first. That taxes twenty domain engineers. They guard something the OGM write path already governs.

The ontology-derived delete-list is fail-closed *for protocols*. This is the case that actually matters. It is not closed-world about domain content.

## Pruning the spec, not the data

`OGM.fetch` accepts an explicit `class_spec=`. Remove the protocol `PropertySpec` entries from the nested spec. Fetch with it. This materializes the shallow shape directly. Verified live:

```
hasValue: []   hasUnit: ['m/s']   accessMode: ['readwrite']
```

The projection therefore happens **before** any connection metadata is read out of the store. It does not filter it out of a materialized model afterwards. That ordering is the point. A data-side filter is a step that can be forgotten. It can be reordered or bypassed by a second code path that materializes its own model. A spec-side prune means the northbound model has no field to carry a broker address in. The generated pydantic model has `extra="forbid"`.

## Two traps in the query, both found by testing

Neither is visible from reading the SPARQL. Each produced a wrong answer that looked plausible:

1. **The parameter property is itself a subproperty of the interface root.** "Everything below the root" therefore matches `tu:hasConveyorSpeed` too. Deleting *its* range removes the value and the unit. This removes the entire northbound payload.
2. **GraphDB materializes reflexive `rdfs:subPropertyOf`** (RDFS rule rdfs6). `subPropertyOf+` behaves like `*`. The interface root matches *itself*. Without excluding it, the root's own range is treated as protocol metadata. `inf:accessMode` is deleted. This is the one interface fact a peer legitimately needs.

Both exclusions are load-bearing and are commented as such at the query.

## Failing closed when the ontology cannot be read

If a property is declared interface-accessible but nothing can be read from its protocol markers' ranges, the projection **raises** rather than serving. This happens with a missing TBox or a range shape not understood. A projection that cannot classify a payload's fields has one safe behavior. Continuing is not it. The failure would surface as a broker address on a public REST route.

Both range shapes the OGM itself accepts are handled. These are an `owl:intersectionOf` list of restrictions and a single bare `owl:Restriction`. Reading only the first would silently miss a one-term protocol contract. A missed term is a leak.

## The binding descriptor's `connection_metadata` becomes a cross-check

It still declares what a binding *reads* to construct a connector. This is genuinely that binding's business. It is no longer the projection's source of truth. Compare the two at construction:

- **Declared only in the ontology** — the contract grew a term this binding ignores. Northbound-safe either way, but the connector may be under-configured.
- **Declared only by the binding** — the code expects a term the ontology does not declare. It will not survive a write. It will not reach the connector. The parameter may come up silently dead. This is the direction that costs debugging time.

Reported, never raised. Drift in either direction is a real deployment state. The projection is already safe because it follows the ontology.

## The prune is unconditional, and that is a security property

ADR 0020 establishes that recognition must run even when nothing is wired. Implementing "no connectors" as "no registry" means no property is recognised as a parameter. The node becomes ordinary data, and it is *shown*. The projection inherits the rule. If pruning were gated on `autoregister_connectors`, the **inspector** would serve broker addresses. This is the least privileged flavour. It wires nothing. The least-privileged instance would leak the most.

Registry construction, recognition and pruning all run for every flavour. Only `connect()` and the sync registration are gated. The regression test that matters is that all three flavours serve byte-identical northbound payloads.

## Scope note: this is not the access-control story

Hiding the broker address stops a peer *learning* how to bypass the middleware. It learns this from the middleware's own REST surface. It does not stop someone who already knows the broker from talking to it. Real access control involves role-based named graphs. It involves placing the middleware, OGM and store in a governed environment. This is deliberate future work. This projection does not claim to provide it.

## Consequences

- **Supersedes ADR 0026's projection claim.** Merge depth remains the right *description* of the two views. The ordering rule it protects is unchanged. It is still load-bearing. Northbound-safe content goes on the parent interface property. Connection details go on the protocol subproperty. Never the other way round. That ordering is now what the projection *reads*. Authoring it correctly matters more than before, not less.
- **Vindicates #42's constraint.** "Do not add a deny-list of southbound field names" was right. The first implementation of this ADR violated it in substance. It appeared not to.
- **Amends ADR 0023's fourth consequence.** "ADR 0019's projection step is not needed" was true when written. It is now false. The rest stands. The binding reads its metadata from the ABox at registration. Recognition runs at construction, before any datamodel exists. The *spec* supplies the effective shape. The ABox supplies the values.
- A merge-depth parameter in `kapps_ogm` (`SAWeindel/kapps_ogm#8`) would let the OGM produce the shallow shape directly. It would retire the prune entirely. Not pursued here. Root ADR 0001 admits only bugfixes to the siblings. It would block #40 behind a cross-repo release.
- Two specs exist per resource. One is the full one the bindings read. The other is the pruned one that is served.
- The middleware's serving path now depends on the interface ontology being present in the store. A future convenience may fetch and seed it from a repository we control. This is filed separately.

## How we got here

The projection was decided four times. Three of the four were correct on the evidence available:

1. **ADR 0019 (2026-07-27, #29)** — *middleware-side, over the materialized data.* Reached after discovering live that a ClassScope cannot select within a parameter. ADR 0018's mechanism did not exist. Correct about the mechanic. Its remedy stripped fields from a materialized model.
2. **ADR 0026 (2026-07-28, #52)** — *there is no projection step. The restriction is the projection.* ADR 0019 retired. Implementation ticket **#51 closed unbuilt**. Sound at the time. The domain TBox declared only `inf:hasValue` and `tu:hasUnit`. `inf:hasMQTTTopic` appeared in no restriction anywhere. The two TBoxes were deliberately unconnected. A broker address was dropped before a datamodel existed. Nothing had to act, because nothing arrived.
3. **This ADR, first version (2026-07-29, #40)** — *the premise died.* Ticket #53 gave the `inf:` interface properties their own ranges. This was necessary and is not reverted. It is what lets provisioning write connection metadata through the OGM. It is what let the seed retire its last raw SPARQL `INSERT`. The metadata then *did* arrive. The remedy pruned the spec. The delete set came from the registry. This was right about the mechanism. It was wrong about the source.
4. **This ADR, current (2026-07-29, grilled from #42's conflict)** — *ask the ontology.* The registry-derived set was shown to fail open for any unregistered protocol.

Two lessons worth keeping:

- **#51 was closed unbuilt on reasoning that a later, correct ontology change invalidated.** A decision resting on "the data never arrives" is only as durable as the schema keeping it away.
- **A constraint on an old ticket outlived the reasoning that produced it.** The #42 "no deny-list" rule was written against a design that no longer existed. It was reasonable to treat as obsolete. It turned out to describe a defect in the replacement. Retiring a stale requirement is not free.

Part of #40 under map #24. It absorbs #29 (ADR 0019). It resolves the conflict raised on #42.
