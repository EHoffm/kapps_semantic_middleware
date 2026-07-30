# A semantic connector is a binding descriptor, registered at construction

A **semantic connector** is any connector that can **register itself from the knowledge graph**. It is
realized not as a connector subclass but as a **binding descriptor**: an object naming the connector
class it builds, the interface property it binds to, the connection metadata its protocol needs, and
how to turn one parameter's metadata into one or more `add_synced_connector` registrations.

> **Consolidated 2026-07-29.** This ADR absorbs **ADR 0016** ("a semantic connector is a bare connector
> + a protocol metadata ontology, resolved through a universal registry"), whose file is deleted. ADR
> 0016's headline was directly contradicted here — a semantic connector is *not* itself an
> `aas_middleware` Connector — so leaving both standing meant the first ADR a reader met on the subject
> told them the wrong thing. What survives from it is below; **How we got here** preserves the route.

```python
@semantic_connector
class MQTTBinding:
    connector_cls       = MqttClientConnector          # sibling class, untouched
    interface_property  = INF.isInterfaceAccessibleMQTTParameter
    connection_metadata = (INF.hasMQTTTopic, INF.hasMQTTBrokerIP,
                           INF.hasMQTTSetTopic, INF.hasMQTTValuePath)

    @staticmethod
    def build(metadata, conn_info, direction):
        broker = metadata[INF.hasMQTTBrokerIP]
        fmt    = ScalarInBlanknode(metadata)           # caches the static facets
        yield Registration(MqttClientConnector(broker, metadata[INF.hasMQTTTopic]),
                           conn_info, SyncDirection.TO_PERSISTENCE, fmt, float)
        if direction is SyncDirection.BIDIRECTIONAL:
            yield Registration(MqttClientConnector(broker, metadata[INF.hasMQTTSetTopic]),
                               conn_info, SyncDirection.FROM_PERSISTENCE, fmt, float)
```

Bindings are built and registered **in the constructor**, from the ClassSpec and the graph — not from
materialized instance data, and not during `on_start_up`.

## Why

### The framework's connectors are the examples, and they are not ours to change

`aas_middleware` ships about ten connectors — MQTT, OPC-UA, HTTP request and polling, websocket and
webhook client and server, AAS client, model. Every one of them is a candidate semantic connector; only
the bare `Connector` protocol is not, being the interface specification itself. Root ADR 0001 forbids
adding self-registration to any of them in the sibling repo, so the capability lives here.

A descriptor referencing `connector_cls` — rather than a mixin subclassing it — is what makes the
extension **universal**. A domain expert can make a vendor's connector semantic without owning or
subclassing its source, and two registration strategies for one protocol (per-topic `MqttClientConnector`
versus a future `BidirectionalMQTTConnector`) sit side by side without sharing an ancestor. A structural
`Protocol` was considered and rejected: since the framework's connectors cannot be annotated to satisfy
it, every one would need an adapter — which is this descriptor under another name, minus registration-time
enforcement.

### One binding, one or two connectors — the framework already models this

`MqttClientConnector` takes a single topic and its `consume()` publishes to the topic it subscribed to,
so it physically cannot serve a read topic plus a distinct `inf:hasMQTTSetTopic`. A settable parameter
therefore needs two connector instances. `ConnectionRegistry.connections` is
`Dict[ConnectionInfo, List[str]]`, so both bind to **one** `ConnectionInfo` and differ only in
`sync_direction` — precisely what `SyncDirection` exists for.

For the TransferUnit that is **4 parameters, 6 topics, 6 framework connectors, 4 bindings**. The ticket's
"one connector per topic" and ADR 0016's "one connector per parameter" were both right, at different
layers.

### The binding depth is forced, and it agrees with ADR 0017

`ConnectionInfo` has exactly three levels — `model_id`, `contained_model_id`, `field_id` — and `field_id`
resolves by plain `getattr`. The deepest addressable thing is therefore the **COMPLEX property**, whose
value is `[AnonymousClass(hasValue=…, hasUnit=…)]`. `inf:hasValue` is unreachable. This is the same
atomic unit ADR 0017 arrived at from the routing side, reached independently from the sync side.

`contained_model_id` resolves through `DataModel.get_model`, which — verified live — indexes belts and
barriers **by IRI even though they are not `Identifiable`**. This is the opposite of the route generator,
which admits only `Identifiable` attributes and therefore sees nothing (#29). The sync machinery works on
the framework as shipped; only the router had to be replaced.

### Static facets are cached, because nothing downstream can read them back

`update_persistence_with_value` does `setattr(contained_model, field_id, value)` — it **replaces the whole
list**. And `Formatter.deserialize(body)` and `Mapper.map(body)` receive only the payload, with no access
to the current persistence value. So an inbound scalar would wipe `hasUnit` and every other facet, and
nothing in the framework's signatures can restore it.

The binding already reads the parameter's metadata to build the connector, so it captures the static
facets there and the formatter reassembles the blanknode from those plus the live value — a pure function
per message, no read of current state, no framework change. ADR 0018 already established that these
facets are static and that a static facet riding in a live payload is free, because `OGM.commit` filters
unchanged triples. A device that genuinely publishes more than a value uses the envelope mode
(`inf:hasMQTTValuePath`), which ADR 0016 already provides.

The formatter also restores symmetry the connector lacks: `receive` runs `json.loads` on the payload while
`consume` publishes its argument raw.

### Registration must happen before startup, or inbound traffic dies silently

`lifespan` calls `connect()` on everything in the connection registry **before** running `on_start_up`
callbacks, and `initiate_sync` — what `add_synced_connector` defers — starts `run_receive()` but never
calls `connect()`. A connector registered while materializing the datamodel (an `on_start_up` callback)
therefore never connects: `MqttClientConnector.client` stays `None`, the listener task never starts, and
its queue is never fed. `receive()` blocks forever. Outbound would limp along, since `consume()`
reconnects on failure — so the failure is one-directional and quiet, the worst kind.

Registering in the constructor avoids it entirely and needs no out-of-band lifecycle call: the framework
connects at step 1 and disconnects at shutdown, and `initiate_sync` is deferred by the framework to
`on_start_up`, where it runs *after* `_load_resource_datamodel` has loaded persistence.

This is possible because everything a `ConnectionInfo` needs comes from the **ClassSpec and the graph** —
which properties are COMPLEX, which match an interface property, which component individuals exist —
not from materialized instance data.

### Direction is the most restrictive of two constraints

A parameter's `inf:accessMode` and the instance's flavour (`connector_sync_direction`, ADR 0020)
constrain direction independently, and neither may widen the other. The read registration is always
emitted; the write registration only when the parameter is `readwrite` **and** the flavour permits
writing. A monitor can therefore never drive a writable belt, and a controller can never write a sensor —
structurally, not by convention. An absent or unrecognised `accessMode` yields read-only, so a parameter
is never writable by accident of omission.

## Consequences

- Amends **ADR 0016**: a semantic connector is a binding descriptor over a connector class, not itself an
  `aas_middleware` Connector, and the concept is universal across the framework's connectors rather than
  MQTT-shaped.
- Amends **ADR 0020**: recognition runs over the **ClassSpec and the graph at construction**, not over the
  materialized datamodel. The disposition rules (recognised parameter / plain data) are unchanged.
- The ticket's binding path `conveyorbelt_left.hasConveyorSpeed.hasValue` is one level too deep and is
  corrected to the COMPLEX property.
- Never bind a `ConnectionInfo` to a blanknode model: `DataModel` assigns them synthetic ids derived from
  memory address (`id_136553861392864`), which do not survive a restart.
- A connector-bound parameter's REST payload is whatever its range restriction declares — domain
  content plus the access-mode marker — and its live value is absent until the device first publishes
  (ADR 0024). The binding reads its connection metadata straight from the ABox at registration, which is
  the moment the middleware joins the domain TBox to the connector's `inf:` TBox.

  > **Corrected 2026-07-29 (ADR 0028).** This consequence originally continued "*a projection step is
  > not needed: connection metadata is never declared in a restriction, so it never materializes*". That
  > became false when #53 gave the `inf:` interface properties their own ranges. The metadata now does
  > materialize, and the northbound projection prunes it out of the ClassSpec before fetching. Reading
  > it from the ABox at registration — the part above — is unaffected and still correct.

## What survives from ADR 0016

**`provide`/`consume` map to read/write of the parameter.** `provide` yields the current value (MQTT:
the latest message on the read topic, held from a subscription); `consume` writes one (MQTT: publish to
the set topic). A `read` parameter uses `provide` only; a `readwrite` parameter uses both. This is how a
connector backs ADR 0015's Path-1 auto-wiring.

**The registry is the extensibility seam.** Adding a protocol is registering a new descriptor — no core
change — and a domain expert may bring their own connector and their own metadata ontology. The `inf:`
bindings this repo ships (MQTT now, OPC-UA reserved) are just the ones that come in the box. This is the
connector-side analogue of ADR 0015's Path-2 escape hatch.

**The MQTT contract** (scenario 3's, an *instance* convention — never baked into the class ontology):

- Metadata: `inf:hasMQTTBrokerIP`, `inf:hasMQTTTopic`, `inf:hasMQTTSetTopic` (present iff `accessMode`
  is `readwrite`), optional `inf:hasMQTTValuePath`.
- Topic scheme `TransferUnit<n>/<component>/<position>/<param>`, setpoint appending `_set`.
- `MockTransferUnit` **publishes 4** and **subscribes to 2**; the middleware is its mirror image.
- Payload: **raw scalar by default**, parsed per the parameter's ontology datatype — which falls out of
  the node model generated from the effective shape, not from hand-written coercion. With
  `inf:hasMQTTValuePath`, a **JSON envelope** read and written at that path, symmetric across both
  directions. Documented at `../mqtt-payloads.md`.

## How we got here

1. **ADR 0016 (2026-07-26, ticket #30)** established the concept — a connector that registers itself
   from the graph — and got two things right that survive: the registry as the extensibility seam, and
   the MQTT contract above. It got two things wrong, both from assuming the framework's connectors were
   ours to extend: that a semantic connector *is* an `aas_middleware` Connector (root ADR 0001 forbids
   adding self-registration to a sibling, so it cannot be), and that resolution keys on the parameter's
   `rdf:type` (ADR 0020: the node has no named type — matching is on the interface property).
2. **ADR 0020 (2026-07-27, ticket #29)** replaced the type key with the interface-property hierarchy.
3. **This ADR (2026-07-27, ticket #28)** replaced "is a Connector" with "names a `connector_cls`", which
   is what makes the extension universal across connectors we neither own nor can subclass.

The through-line: each step moved the seam *outward*, away from requiring anything of the code being
integrated.

Resolves wayfinder ticket #28 under map #24; absorbs #30 (ADR 0016).
