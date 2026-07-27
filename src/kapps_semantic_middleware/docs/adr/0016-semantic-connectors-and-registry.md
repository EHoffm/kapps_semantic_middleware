# A semantic connector is a bare connector + a protocol metadata ontology, resolved through a universal registry

The middleware reaches a physical resource through a **semantic connector**: an aas_middleware
`Connector` (the four methods `connect` / `disconnect` / `provide` / `consume`, ADR 0006) paired with
a **protocol metadata ontology** — the interface class it serves (ADR 0015, e.g. `inf:MQTTParameter`)
and a **ClassScope** projecting the connection metadata that protocol needs. A universal **connector
registry** maps interface class → semantic connector; the middleware, seeing a parameter typed
`inf:MQTTParameter`, looks up the connector, fetches its metadata ClassScope off the parameter, and
calls `connect`. **MQTT is the first registered connector, not a special case** — #30 is really the
registry framework, worked through the mock PLC.

## Why

**Extend the bare Connector, don't reinvent it.** aas_middleware already defines a `Connector` as
anything with `connect`/`disconnect`/`provide`/`consume` (ADR 0006's `KnowledgeGraphConnector` is
one). The only thing missing for it to be *self-wiring from the graph* is a declaration of *what
metadata it needs to connect*. A semantic connector adds exactly that: **semantic connector = bare
connector + protocol metadata ontology**. Nothing about the transport is re-specified.

**The metadata declaration is a ClassScope, reusing #38's view primitive.** A connector's "what I
need to connect" is a projection over a parameter's metadata — precisely a `ClassScope` (ADR 0015).
The MQTT connector declares the scope `{ inf:hasMQTTBrokerIP, inf:hasMQTTTopic, inf:hasMQTTSetTopic,
inf:hasMQTTValuePath }`; the middleware fetches that scope off the parameter and hands it to
`connect`. This makes required metadata **self-describing and validatable** — a parameter can be
checked against its connector's scope before wiring — rather than buried in connector code, and it is
the same primitive by which "is-this-settable" is a view.

**A universal registry keyed on the interface class.** Resolution is `parameter rdf:type → interface
class → semantic connector`. Adding a protocol is registering a new semantic connector (new interface
class + metadata scope + four-method implementation) — no core change. The registry is the
extensibility seam that lets a domain expert bring their *own* connector and metadata ontology (the
connector-side analogue of ADR 0015's Path-2 `@state`): the standard `inf:` connectors (MQTT now,
OPC-UA reserved) are just the ones this repo ships.

**`provide`/`consume` map to read/write of the parameter.** `provide` yields the current value (MQTT:
the latest message on the read topic, held from a subscription); `consume` writes a value (MQTT:
publish to the set topic). A read-only parameter uses `provide` only; a `readwrite` parameter (ADR
0015 access-mode facet) uses both. This is how a connector backs **Path-1** auto-wiring (ADR 0015):
the datamodel field is fed by `provide` and flushed by `consume`.

## The MQTT connector (worked example / scenario3 contract)

- **Interface class** `inf:MQTTParameter`; **metadata scope** = broker IP, read topic
  (`inf:hasMQTTTopic`), set topic (`inf:hasMQTTSetTopic`, present iff `accessMode` is `readwrite`),
  optional `inf:hasMQTTValuePath`.
- **Topic scheme (instance convention, not baked in the class ontology):**
  `TransferUnit<n>/<component>/<position>/<param>`; the setpoint appends `_set`.
- **The `MockTransferUnit` contract** (the edge-device PLC stand-in) **publishes 4**
  (`…/ConveyorBelt/left/speed`, `…/ConveyorBelt/right/speed`, `…/LightBarrier/front/occupied`,
  `…/LightBarrier/back/occupied`) and **subscribes to 2** (`…/ConveyorBelt/{left,right}/speed_set`).
  The middleware is the mirror image: subscribes the 4, publishes the 2.
- **Payload:** **raw scalar by default**, parsed per the parameter's ontology datatype (`xsd:double`
  speed, `xsd:boolean` occupancy). If **`inf:hasMQTTValuePath`** is present, the payload is a **JSON
  envelope** and the connector reads/writes the value at that path — one optional property, symmetric
  across `provide`/`consume`, that makes the same connector fit arbitrary cluster payloads. Documented
  alongside the connector.

## Consequences

- Adds `inf:hasMQTTSetTopic` and `inf:hasMQTTValuePath` to the MQTT interface class's metadata — both
  feed the capstone-#39 `inf:` vocabulary.
- The semantic-connector + registry framework is **core middleware**, consumed by #28 (the 6-topic
  wiring) and #29 (datamodel materialization off `provide`). The concrete build — `MockTransferUnit`,
  the MQTT semantic connector, the registry — is a `ready-for-agent` handoff, **gated by the
  consolidation capstone #39** (no implementation before it).
- **Open (ADR 0015 row 3):** auto-provisioning a *new* connection when an instance lacks metadata —
  where the topic/broker come from — is deferred to the mock-PLC / bootstrap work (#35); scenario3's
  instances carry their metadata explicitly.

Resolves wayfinder ticket #30 under map #24.
