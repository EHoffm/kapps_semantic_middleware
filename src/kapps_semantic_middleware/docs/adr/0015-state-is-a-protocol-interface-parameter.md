# A resource's state is a protocol-interface parameter, wired ontology-first

A resource's readable and settable state is modeled as an **interface-accessible parameter**. One graph
node carries its value and unit. The node also carries the metadata a protocol connector needs to reach the device.
The middleware's former `svc:StateProperty` (a readable thing with a REST endpoint) and the shop-floor
**parameter** (an MQTT/OPC-UA-accessible value) are **the same thing seen from two directions**. They
collapse into one concept.

```turtle
tui:ConveyorBelt1_left  tu:hasConveyorSpeed  [ tu:hasUnit "m/s" ;
                                               inf:accessMode "readwrite" ;
                                               inf:hasMQTTTopic    "TransferUnit1/ConveyorBelt/left/speed" ;
                                               inf:hasMQTTSetTopic "TransferUnit1/ConveyorBelt/left/speed_set" ;
                                               inf:hasMQTTBrokerIP "127.0.0.1" ] .
```

> **Consolidated 2026-07-29.** This ADR absorbs **ADR 0013** ("settable state is
> `svc:SettableStateProperty`") and **ADR 0014** ("StateProperties are marks over the datamodel"), both
> of which it superseded in part. Their files are deleted. Everything below that is still load-bearing
> came from them. The *chain of thought* that led here is preserved in **How we got here** at the
> end. Read this ADR alone to know what is true.

## Why

### A setpoint is not a Workflow

*(from ADR 0013 — still the reason parameters and workflows are different mechanisms)*

Setting a setpoint was considered as an ordinary `svc:Workflow`. It would be a `tu:SetConveyorSpeed` workflow
realizing a "set" Capability, dispatched as an Operation through the event-trigger queue (ADR 0009).
This approach was rejected. A conveyor-speed setpoint is an idempotent, high-frequency control variable, not a discrete
task with a `queued → running → done` lifecycle and per-invocation provenance. Modeling it as a
Workflow fragments one quantity into a read-side and a write-side. A discoverer must find
them separately and *know* they are the same value. This approach wraps every speed nudge in an Operation individual.

This is the standing split: **states are declarative (the ontology), workflows are imperative
(`@mw.workflow`)**.

### Settable is a facet, not a subclass — and "mutable" names the wrong axis

Whether a parameter is externally settable is metadata on the one node: `inf:accessMode`, valued
`"read"` or `"readwrite"`.

Two earlier cuts were rejected. A symmetric `ReadOnlyStateProperty`/`SettableStateProperty` pair
misnames the distinction. A read-only sensor value (a light barrier going blocked → clear) mutates
constantly, so the axis is not mutable-vs-immutable but **whether a consumer may write**. A
`SettableStateProperty rdfs:subClassOf StateProperty` specialization, while correctly named, produces a
protocol × direction class explosion once more than one protocol exists.

A facet avoids both. It mirrors OPC-UA access levels, and is exactly what an "is this settable?" view
reads. There are **no capabilities** for states. A "LightBarrierCapability" is meaningless, and the
authoritative sfb1574 ontology has none either.

### Ground truth in the graph, never a decorator flag

*(from ADR 0013, generalized)*

The data carries settability, not a Python argument. `@mw.state` takes no `settable=` flag, the
same way `@mw.workflow` takes no `is_workflow=`. Discovery of "what can I set" is a plain graph query.
This is ADR 0003's rule applied to parameters.

### The setter surface already exists — reuse it

*(from ADR 0014 — live, and the seam connectors hook into)*

Rather than invent a `PUT /state/{name}`, reads and writes reuse `aas_middleware`'s generated CRUD REST
API, which exposes `PUT /{Model}/{id}/{attribute}/` implemented as `provide() → setattr →
connector.consume` (`aas_middleware/middleware/rest_routers.py`). **That `connector.consume` step is
precisely the seam the outbound MQTT connector hooks** (ADR 0023). A parallel setter route would
duplicate the machinery and bypass the seam.

Consequently a set is a synchronous `PUT` to the discovered endpoint. It uses **direct REST, not
Operation-routed**: no `cfc:Operation`, no event-trigger queue, consistent with scenario 2's
discover-and-invoke pattern.

### One backing store, not two

*(from ADR 0014)*

A getter-backed read surface plus a datamodel-backed write surface would be two sources of truth for one
value, needing reconciliation. Unifying on the datamodel removes the split. The value lives in one
place, fed by the device through a connector and read/written through the framework CRUD.

Whether the value is *also* persisted to the graph is **the domain's choice, not a middleware
invariant** (ADR 0024). Under the *locator* pattern the graph records only where the value lives.
Under the *committed value* pattern a slowly-changing parameter is legitimately committed.

### Access mode gates the verbs — structurally, not by advice

*(from ADR 0014, re-based onto the facet)*

A `readwrite` parameter exposes `GET`+`PUT` and gets an outbound connector. A `read` parameter exposes
`GET` only, with no `PUT` route and no outbound connector. A sensor is therefore **structurally**
unwritable through the advertised surface. ADR 0023 carries this into the connector layer. Direction is
the most restrictive of `accessMode` and the instance's connector wiring. An absent or unrecognized
access mode yields read-only. A parameter is therefore never writable by accident of omission.

### Ontology-first wiring; `@state` is the escape hatch

The parameter — its connection metadata, access mode, and datatype — is fully authored in the
domain ontology. The generic runtime therefore reads it and wires everything. There is **no per-parameter
decorator by default**. `@mw.state` is demoted from *the standard* to *a feature*. It is the `@property`-style
escape hatch for when retrieval or actuation is more complex than a direct connector mapping. The common
case is zero-Python, which is what matters at twenty domain engineers to one ontology engineer (ADR
0003).

### Exposure is by explicit mark — where a decorator is used at all

*(from ADR 0014)*

Where `@mw.state` *is* used, only marked fields become discoverable in the graph. The datamodel carries
plumbing (ids, counters, heartbeats) that is not semantic state. Auto-promoting every field would
re-introduce the auto-derivation ADR 0003 rejected and flood the graph.

## Decision: startup wiring is Open-World-aware

The TBox permitting a protocol never implies a given *instance* carries it, so the switch reads the
**instance**, not the class. Per parameter, at setup:

| Instance has connection metadata? | `@state` bound? | Behaviour |
|---|---|---|
| **Yes** | No | **Path 1 (auto)** — wire the connector from the instance's metadata. |
| **Yes** | Yes | **Conflict** — warn: the instance is auto-wireable *and* custom code is bound. |
| **No** | No | **Auto-provision** — wire a new connection and persist its metadata onto the instance. |
| **No** | Yes | **Path 2 (custom)** — `@state` backs get/set, and exposure metadata is written back. |

**Write-back rule:** whatever the middleware wires, it persists to the graph, so the KG reflects running
reality and peers can discover it.

Row 3 is the provisioning flow, tracked as
[#54](https://github.com/EHoffm/kapps_semantic_middleware/issues/54). Rows 1 and 3 are what ADR 0026's
per-instance interface resolution and ADR 0028's registry-driven wiring implement.

## Consequences

- **`svc:StateProperty` / `svc:SettableStateProperty` retire** into the interface-accessible parameter
  model. The `providesCapability` link goes with them.
- **The getter-backed `/state/{name}` route is retired** — decided here, **not yet done**. The route and
  `build_state_endpoint` still exist in `middleware.py`/`registration.py`, and scenario 2 still serves
  `door_status` through them. Tracked as
  [#48](https://github.com/EHoffm/kapps_semantic_middleware/issues/48) and
  [#37](https://github.com/EHoffm/kapps_semantic_middleware/issues/37). Until they land, the repo
  demonstrates a superseded surface.
- **Consolidation direction.** The concepts merge into one central ontology taking the `inf:` name (the
  INF project owns that prefix in the SFB1574 cluster). This is recorded as direction. The migration is
  [#39](https://github.com/EHoffm/kapps_semantic_middleware/issues/39). **Note the 2026-07-27 inversion:
  #39 no longer gates implementation**. Each mechanism is a validation gate *on* the consolidation, and
  #40 shipped ahead of it.
- SHACL validation of a write payload stays out of scope. This is deferred with SHACL Interop (ADR 0025 fixes
  where the one closed-world moment belongs).

## Corrections absorbed since this ADR was first written

Recorded here so the ADR does not have to be read against three others to be trusted:

- **The parameter node carries no named `rdf:type`.** This ADR originally typed it
  `a inf:MQTTParameter` and paired an *interface class* one-to-one with a connector. **ADR 0020
  corrected that**. The node's only types are anonymous restriction nodes. These exist by inference
  and never survive an explicit-graph fetch. Recognition therefore matches on the **interface property**
  hierarchy (`tu:hasConveyorSpeed ⊑ inf:isInterfaceAccessibleMQTTParameter`) instead. The protocol-extensibility
  seam survives unchanged. A new protocol is a new interface property plus a new binding, no core
  change. Only the thing matched on moved.
- **`ClassScope` is not the view *within* a parameter.** This ADR claimed ClassScope was the projection
  mechanism for the southbound/northbound split. **ADR 0019 disproved it** (a ClassScope cannot select
  within a parameter — `_fetch_complex_property` is an unfiltered `?bnode ?property ?value`), and
  **ADR 0028** settled where the projection actually lives. The middleware prunes the ClassSpec before
  fetching. ClassScope still selects *which* parameters, never which parts of one.
- **No `inf:hasValue` in a locator's instance data.** The original worked example carried
  `inf:hasValue 12.1`. ADR 0024 scopes that to the committed-value pattern, and scenario 3 as a locator
  carries no value literals at all.

## How we got here

The route this decision actually walked, preserved from the two ADRs consolidated into it:

1. **ADR 0013 (2026-07-23, ticket #26)** asked how to model *settable* state and answered
   `svc:SettableStateProperty rdfs:subClassOf svc:StateProperty`. It proposed one new class, settability inferred
   from the type, no flag. Its rejections still stand (not a Workflow, not a mutable/immutable pair).
   Its vocabulary does not.
2. **ADR 0014 (2026-07-23, ticket #27)** asked what REST surface a setter gets and answered: none of its
   own. A StateProperty is a *mark over a datamodel field*, reusing the framework CRUD, retiring
   `/state/{name}`. The mechanism survived. The decorator-as-standard did not.
3. **ADR 0015 (2026-07-23, ticket #38)** collapsed both into one concept. The #25 review found that the
   authoritative sfb1574 ontology models each state as a metadata blank node. It has **no** capabilities
   and **no** StateProperty subclasses. Settability became a facet, and wiring became ontology-first.

Resolves wayfinder ticket #38 under map #24. Absorbs #26 (ADR 0013) and #27 (ADR 0014).
