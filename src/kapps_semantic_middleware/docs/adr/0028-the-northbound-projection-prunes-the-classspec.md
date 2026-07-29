# The northbound projection prunes the ClassSpec

The middleware builds its northbound view by **removing the southbound properties from the `ClassSpec`
before fetching**, and passing that pruned spec to `OGM.fetch(class_spec=…)`. The set of southbound
properties is the union of every registered binding descriptor's `connection_metadata`. The pruning
runs **unconditionally**, for every flavour, including one that wires no connectors at all.

> **Consolidated 2026-07-29.** This ADR absorbs **ADR 0019** ("the northbound projection is
> middleware-side; a ClassScope cannot select within a parameter"), whose file is deleted. The
> projection question was decided three times in five days — ADR 0019, then ADR 0026, then here — and
> reconstructing the answer from three documents was itself a hazard. Everything still true is below;
> **How we got here** preserves the route.

## The mechanic that constrains every answer

*(established by ADR 0019, reproduced live against `tui:TransferUnit1` under ticket #29, and still
true)*

**A `ClassScope` selects which parameters a consumer sees. It cannot select within one.** Three
mechanics in `kapps_ogm` combine to make a parameter node's contents fixed and identical for every
consumer:

1. `OGM._fetch_complex_property` issues a bare `?bnode ?property ?value` — every property of the node,
   no filter, no scope consulted.
2. `PropertySpec.specify` routes a `COMPLEX` property to `_specify_complex_property`, which takes no
   `nested_scope` argument at all. A chain element below a complex property is dropped silently — not
   even a warning.
3. The node's shape therefore comes entirely from the property's `rdfs:range` restriction — the TBox.

ADR 0018's worked example, which scoped three levels deep to reach `INF.hasValue` and `TU.hasUnit`
inside the parameter, was silently discarded when run. That example was corrected in place.

This is why `inf:accessMode` — which a peer legitimately needs — has to be **declared in a
restriction** rather than filtered in per consumer, and it is why the projection cannot be expressed as
a view "simply declining to fetch" the connection metadata. Something has to act.

## Why

### "The restriction is the projection" is not true as built

ADR 0026 concluded that a view is a *merge depth*: a consumer merging only up to
`inf:isInterfaceAccessibleParameter` sees value, unit and access mode, and only one that also merges the
protocol subproperty `inf:isInterfaceAccessibleMQTTParameter` sees topic and broker. On that reading the
northbound datamodel *physically cannot* carry a broker address and no filtering step is needed — which
is why ADR 0019 was retired and #51 closed unbuilt.

The premise does not hold against the implementation. `PropertySpec._resolve_effective_ranges` walks the
**entire** `rdfs:subPropertyOf*` chain and merges every anonymous range it finds. There is no merge-depth
parameter on `PropertySpec.specify`, on `OGM.get_class_spec`, or on `OGM.fetch`. Every ClassSpec is the
full merge, so there is exactly one shape per property and it is the southbound one.

Measured live against the seeded scenario-3 belt, materializing under a scope over
`tu:hasConveyorSpeed`:

```
hasValue:        []
hasUnit:         ['m/s']
hasMQTTTopic:    ['TransferUnit1/ConveyorBelt/left/speed']     <- southbound
hasMQTTBrokerIP: ['127.0.0.1']                                 <- southbound
hasMQTTSetTopic: ['TransferUnit1/ConveyorBelt/left/speed_set']  <- southbound
accessMode:      ['readwrite']
```

This is the exact bypass the IT-OT boundary exists to prevent: a peer that GETs the resource learns the
broker address and both topics, and can drive the device without going through the middleware at all.

The gap opened when `#53` (2026-07-28) gave the `inf:` interface properties their own `rdfs:range`
restrictions. That was necessary and is not being reverted — it is what lets provisioning write
connection metadata through the OGM at all, and retiring the last raw-SPARQL write depended on it. But
it invalidated ADR 0023's consequence that "connection metadata is never declared in a restriction, so it
never materializes". Both halves of the old reasoning are now false at once.

### Pruning the spec, not the data

`OGM.fetch` accepts an explicit `class_spec=`. Removing the southbound `PropertySpec` entries from the
nested spec and fetching with it materializes the shallow shape directly — verified live, same belt:

```
hasValue:   []
hasUnit:    ['m/s']
accessMode: ['readwrite']
```

So the projection happens **before** any connection metadata is read out of the store, rather than by
filtering it out of a materialized model afterwards. That ordering is the point. A data-side filter is a
step that can be forgotten, reordered, or bypassed by a second code path that materializes its own model;
a spec-side prune means the northbound model has no field to carry a broker address in. The pydantic
model generated from the pruned spec has `extra="forbid"`, so an attempt to put one there raises.

This is ADR 0019's middleware-side projection returning, but moved one layer up — from the instance data
to the shape. ADR 0019 stays retired **as written** (it projected materialized data); this supersedes
ADR 0026's claim that no projection step exists.

### The registry already knows which properties are southbound

A binding descriptor declares `connection_metadata` — for MQTT, `inf:hasMQTTTopic`,
`inf:hasMQTTBrokerIP`, `inf:hasMQTTSetTopic`, `inf:hasMQTTValuePath`. That tuple exists so the binding can
read what its protocol needs; it is also, exactly, the set of properties that must never go north. So the
prune set is the union over the registry and needs no new declaration, no new ontology term, and no
hardcoded list in the core. A domain expert registering a connector for their own protocol gets the
projection for their terms for free, which is the property that makes this scale to twenty domain
engineers and one ontology engineer.

It also keeps ADR 0021 intact: the core names no protocol term, because it asks the registry.

### The prune is unconditional, and that is a security property

ADR 0020 already establishes that recognition must run even when nothing is wired: implementing
"no connectors" as "no registry" means no property is recognised as a parameter, the blank node becomes
ordinary data, and it is *shown*. The projection inherits the same rule for the same reason. If pruning
were gated on `autoregister_connectors`, the **inspector** flavour — the least privileged, wiring
nothing — would be the one serving broker addresses northbound. The least-privileged instance would leak
the most.

Registry construction, recognition and pruning therefore all run for every flavour. Only `connect()` and
the sync registration are gated. The regression test that matters is that all three flavours serve
byte-identical northbound payloads.

## Consequences

- **Supersedes ADR 0026's projection claim.** Merge depth remains the right *description* of the two
  views, and the ordering rule it protects is unchanged and still load-bearing: northbound-safe content
  on the parent interface property, connection details on the protocol subproperty, never the other way
  round. What changes is that the middleware must *realize* the shallow view by pruning, because the OGM
  only ever computes the deep one.
- **Amends ADR 0023's fourth consequence.** "ADR 0019's projection step is not needed" was true when
  written and is now false. The rest of that consequence stands unchanged: the binding reads the
  connection metadata **from the ABox at registration**, which is the moment the middleware joins the
  domain TBox to the connector's `inf:` TBox. It has to — recognition runs at construction, before any
  datamodel exists to read it from. What the *spec* supplies is the effective shape: only properties the
  resolved restriction declares are kept, since a property the restriction does not declare would not
  survive a write either, and binding to one would yield a connector whose values silently vanish.
- A merge-depth parameter in `kapps_ogm` would let the OGM produce the shallow shape directly and make
  the prune unnecessary. It was considered and not pursued: root ADR 0001 admits only bugfixes to the
  siblings, this is a feature, and it would block #40 behind a cross-repo release. The prune is local,
  testable here, and cheap to retire later — it is one function and its call site.
- The southbound spec is still built, once, and is what the bindings read. Two specs exist per resource:
  the full one for wiring and the pruned one for serving.

## How we got here

The projection was decided three times. Preserving the route matters, because two of the three answers
were correct on the evidence available when they were written:

1. **ADR 0019 (2026-07-27, ticket #29)** — *the projection is middleware-side, over the materialized
   data.* Reached after discovering live that a ClassScope cannot select within a parameter, so ADR
   0018's mechanism did not exist. Correct about the mechanic; its chosen remedy was to strip fields
   from a materialized model.
2. **ADR 0026 (2026-07-28, ticket #52)** — *there is no projection step; the restriction is the
   projection.* ADR 0019 was retired and its implementation ticket **#51 closed unbuilt**. The reasoning
   was sound at the time: the domain TBox declared only `inf:hasValue` and `tu:hasUnit`, put
   `inf:hasMQTTTopic` in no restriction anywhere, and the two TBoxes were deliberately unconnected — so
   a broker address was dropped before a datamodel existed. Nothing had to act, because nothing arrived.
3. **This ADR (2026-07-29, ticket #40)** — *the premise died.* Ticket **#53** gave the `inf:` interface
   properties their own `rdfs:range` restrictions, which was necessary and is not being reverted: it is
   what lets provisioning write connection metadata through the OGM at all, and it is what let the seed
   retire its last raw SPARQL `INSERT`. The moment those ranges existed, the metadata *did* arrive, and
   `_resolve_effective_ranges` merges the whole `subPropertyOf*` chain with no depth control. Measured,
   not inferred: the served belt carried topic, set topic and broker.

The lesson worth keeping: **#51 was closed unbuilt on reasoning that a later, correct ontology change
invalidated.** A decision that rests on "the data never arrives" is only as durable as the schema that
keeps it away — and here the schema had to change for an unrelated and better reason.

ADR 0019 and this ADR agree that the middleware must act; they disagree only on *what* it acts on, and
acting on the shape rather than the data is the stronger form.

Part of #40 under map #24; absorbs #29 (ADR 0019).
