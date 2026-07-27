# A resource's state is a protocol-interface parameter, wired ontology-first

A resource's readable/settable state is modelled as an **interface-accessible parameter** — one
graph node carrying its value/unit **and** the metadata a protocol connector needs to reach the
device. The middleware's former `svc:StateProperty` (a readable thing with a REST endpoint) and
the shop-floor **parameter** (an MQTT/OPC-UA-accessible value) are **the same thing seen from two
directions**; they collapse into one concept. This supersedes the StateProperty model of ADR 0013
and 0014.

Worked example (the authoritative `transferunit` ontology):

```turtle
tui:ConveyorBelt1_left  tu:hasConveyorSpeed  [ a inf:MQTTParameter ;
                                               inf:hasValue 12.1 ; tu:hasUnit "m/s" ;
                                               inf:hasMQTTTopic "ConveyorBelt1/left/speed" ;
                                               inf:hasMQTTBrokerIP "127.0.0.1" ;
                                               inf:accessMode "readwrite" ] .   # settable
```

## Why

### Two views on one node — and ClassScope *is* the view

The `topic`/`broker` metadata is **southbound** (how the *middleware* reaches the PLC); discovery
and settability are **northbound** (how *peers* reach the middleware). These are not two nodes or
two classes — they are two **projections** of one parameter node, and the OGM's **`ClassScope`**
(`kapps_ogm/utils/class_scope.py`) is exactly the projection mechanism: a tree of property-chains
selecting which (nested) metadata to fetch. *"Give me the MQTT-connection metadata"* is one
ClassScope; *"tell me whether this parameter is externally settable"* is another, over the very
same node. Making ClassScope the load-bearing "view" primitive is the reason one central ontology
can serve both the IT-OT boundary and the control/factory layer without duplicating concepts.

### Metadata lives on a blanknode the OGM already understands

A parameter property points to a **blanknode bundling its metadata** (value, unit, connection
info) — the pattern kept from the (now-deprecated) CrcInterfaces ontology. This is not new
machinery: the OGM's **complex property** support (`PropertyValueKind.COMPLEX`,
`property_spec.py`) already materializes a property whose range is a blanknode class expression
(`owl:intersectionOf (hasValue …)(hasUnit …)`) into a nested typed structure.

### Interface class ↔ connector is the protocol-extensibility seam

The parameter is typed by a **protocol interface class** — `inf:InterfaceAccessibleParameter`
(protocol-agnostic core) with subclasses `inf:MQTTParameter`, `inf:OPCUAParameter`, … Each
interface class declares *what connection metadata that protocol needs* (MQTT: topic + broker;
OPC-UA: endpoint/url/namespace/variableId) and is paired **one-to-one with a connector** in the
middleware. Adding a protocol = a new interface class + a new connector, no core change.

### Settable is a *facet*, not a subclass

Whether a parameter is externally settable is metadata on the one node (an access mode, e.g.
`inf:accessMode "read" | "readwrite"`), which a ClassScope projects. This **supersedes ADR 0013's
`svc:SettableStateProperty` subclass**: a facet avoids a protocol×direction class explosion, mirrors
OPC-UA access levels, and is what a "is-this-settable" view actually reads. There are **no
capabilities** for states (a "LightBarrierCapability" is meaningless — the #25 review correction).

### The ontology is ground truth, so wiring is ontology-first; `@state` is the escape hatch

Because the parameter (type, connection metadata, access mode, datatype) is fully authored in the
domain ontology, the generic middleware runtime can read it and wire everything. So there is **no
per-parameter decorator by default**. `@mw.state` is demoted from *the standard* to *a feature* —
the `@property`-style escape hatch for when retrieval/actuation is more complex than a direct
connector mapping. This gives a clean split: **states are declarative (ontology); workflows are
imperative (`@mw.workflow`)** — and it keeps the common case zero-Python, which matters at twenty
domain engineers to one ontology reviewer (ADR 0003). It **supersedes ADR 0014's** decorator-as-
standard while keeping its datamodel/CRUD mechanism as Path 1.

## Decision: startup wiring (Open-World-aware)

The TBox permitting a protocol never implies a given *instance* carries it, so the switch reads the
**instance**, not the class. At fetch/setup of a resource instance, per parameter:

| Instance has connection metadata in KG? | `@state` bound? | Behaviour |
|---|---|---|
| **Yes** | No | **Path 1 (auto)** — wire the connector from the instance's metadata. |
| **Yes** | Yes | **Conflict** — log a warning (or error): instance is auto-wireable *and* custom code is bound. |
| No (TBox permits the protocol) | No | **Auto-provision** — wire a *new* connection and **persist its connection metadata** onto the instance in the KG. |
| No | Yes | **Path 2 (custom)** — `@state` backs get/set, **and** exposure metadata is written onto the instance in the KG for discovery. |

**Write-back rule:** whatever the middleware wires — provisioned connection or `@state` exposure —
it **persists to the graph**, so the KG reflects the running reality and peers can discover it.

## Consequences

- **`svc:StateProperty`/`SettableStateProperty` retire** into `inf:InterfaceAccessibleParameter` +
  protocol subclasses; the `providesCapability` link goes (no state capabilities).
- **Amends ADR 0013** (settable = facet, not subclass) and **ADR 0014** (StateProperty-datamodel
  mark → Path 1; `@state` → Path 2 escape hatch). Their `ready-for-agent` handoffs (#36, #37) are
  superseded/absorbed here.
- **Consolidation (directional).** The concepts merge into **one central ontology that takes the
  `inf:` name** (the INF project owns that prefix in the SFB1574 cluster; domain experts navigate by
  it) but **carries most of `svc:`'s concepts**. This is recorded as direction; the repo-wide
  `svc:`→`inf:` migration is a **capstone** that runs *after all scenario3 grilling* (to absorb every
  learning) and *before any implementation* — it gates the whole `ready-for-agent` set.
- The `transferunit.ttl` (#25) is re-authored on this model: reuse the fixed `transferunit` topology
  + metadata blanknodes (real MQTT topics), no capabilities, `inf:` prefix.
- **Open item:** row 3's auto-provision source — where the *new* connection's topic/broker come from
  when the instance has none (convention from the IRI? a class-level default? config?). Likely the
  mock-PLC provisioning flow (#30 / #35); resolve there.

Resolves wayfinder ticket #38 under map #24.
