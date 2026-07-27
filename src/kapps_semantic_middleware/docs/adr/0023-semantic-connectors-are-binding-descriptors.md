# A semantic connector is a binding descriptor, registered at construction

A **semantic connector** is any connector that can **register itself from the knowledge graph**. It is
realized not as a connector subclass but as a **binding descriptor**: an object naming the connector
class it builds, the interface property it binds to, the connection metadata its protocol needs, and
how to turn one parameter's metadata into one or more `add_synced_connector` registrations.

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
  (ADR 0024). **ADR 0019's projection step is not needed**: connection metadata is never declared in a
  restriction, so it never materializes. The binding reads it straight from the ABox at registration,
  which is the moment the middleware joins the domain TBox to the connector's `inf:` TBox.

Resolves wayfinder ticket #28 under map #24.
