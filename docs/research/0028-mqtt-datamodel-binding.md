# #28 — How MQTT binds to the resource datamodel

Research output for wayfinder ticket
[#28](https://github.com/EHoffm/kapps_semantic_middleware/issues/28) under map #24. Verified against
`aas_middleware_inf` and, for the datamodel half, live against `tui:TransferUnit1` in the `OGM`
repository on 2026-07-27. Companion to `0029-datamodel-at-startup.md`.

## Answer

**4 parameters → 4 bindings → 6 framework connectors → 6 topics.** Each binding is one
`ConnectionInfo`; a settable parameter registers two connectors against it, differing only in
`sync_direction`.

```python
ConnectionInfo(data_model_name="resource",
               model_id="…TransferUnitInstances#TransferUnit1",
               contained_model_id="…TransferUnitInstances#ConveyorBelt1_left",
               field_id="«TU»_hasConveyorSpeed")     # ← the COMPLEX property, not hasValue
```

| parameter | accessMode | topics | registrations |
|---|---|---|---|
| `ConveyorBelt1_left` / `hasConveyorSpeed` | readwrite | `…/left/speed`, `…/left/speed_set` | `TO_PERSISTENCE`, `FROM_PERSISTENCE` |
| `ConveyorBelt1_right` / `hasConveyorSpeed` | readwrite | `…/right/speed`, `…/right/speed_set` | `TO_PERSISTENCE`, `FROM_PERSISTENCE` |
| `LightBarrier1_front` / `isOccupied` | read | `…/front/occupied` | `TO_PERSISTENCE` |
| `LightBarrier1_back` / `isOccupied` | read | `…/back/occupied` | `TO_PERSISTENCE` |

## The eight mechanics

### 1. `ConnectionInfo` has exactly three levels

`model_id` / `contained_model_id` / `field_id` (`middleware/registries.py`). `field_id` resolves by
plain `getattr`/`setattr` (`middleware/sync/synchronization.py`), so the deepest addressable thing is
the **COMPLEX property**. `inf:hasValue` is one level below and unreachable.

This is the same atomic unit ADR 0017 reached from the routing side — arrived at independently from
the sync side. The ticket's proposed binding `conveyorbelt_left.hasConveyorSpeed.hasValue` is one
level too deep.

### 2. The payload is a list, never a scalar

`getattr(belt, "«TU»_hasConveyorSpeed")` → `[AnonymousClass(«INF»_hasValue=[12.1], «TU»_hasUnit=["m/s"])]`.
Every RDF value is a list, including scalars.

### 3. `contained_model_id` resolves even though belts are not `Identifiable`

`DataModel.from_models(instance).get_model("…ConveyorBelt1_left")` **succeeds** — verified live. The
`DataModel` indexed all six models (2 belts, 2 barriers, the unit, and one blanknode).

This is the **opposite** of #29's route-generation finding: `get_contained_models_attribute_info`
admits only attributes passing `is_identifiable_type` and therefore returns `[]`, while `DataModel`
indexing does not require it. **The sync machinery works on the framework as shipped; only the router
had to be replaced (#41).**

### 4. `MqttClientConnector` is one topic, and publishes where it subscribes

`MqttClientConnector(broker_ip, topic, port)`: `connect()` subscribes and spawns a listener;
`consume(body)` publishes to `self.topic` — the same topic. It physically cannot serve a read topic
plus a distinct `inf:hasMQTTSetTopic`, so a settable parameter needs **two** instances.

### 5. Many connectors may share one binding

`ConnectionRegistry.connections` is `Dict[ConnectionInfo, List[str]]`. Both connectors bind to one
`ConnectionInfo` and differ only in `sync_direction` — exactly what `SyncDirection` exists for. So the
ticket's "one connector per topic" and ADR 0023's "one connector per parameter" are both right, at
different layers.

### 6. The connector is asymmetric

`listen_for_mqtt_messages` runs `json.loads(message.payload.decode())`; `consume` publishes its
argument raw. The formatter must restore symmetry. Note a bare scalar survives `json.loads` only if it
is valid JSON — `12.1` parses, `on` does not.

### 7. Nothing downstream can read the previous value back

`update_persistence_with_value` does `setattr(contained_model, field_id, value)` — replacing the whole
list — and `Formatter.deserialize(body)` / `Mapper.map(body)` receive **only the payload**. So an
inbound scalar would wipe `hasUnit` and every other facet, and no framework signature can restore it.

Hence static facets are cached at wiring time and the formatter reassembles the node (ADR 0023). A
device that genuinely publishes more than a value uses ADR 0023's `inf:hasMQTTValuePath` envelope.

### 8. Registration after startup silently kills inbound traffic

`lifespan` (`middleware/middleware.py`) runs in this order:

```
1. connect() every connector in connection_registry
2. connect() every persistence connector
3. start on_startup workflows
4. run on_start_up callbacks      ← _load_resource_datamodel lives here
```

and `initiate_sync` — what `add_synced_connector` defers — starts `run_receive()` but **never calls
`connect()`**. A connector registered at step 4 therefore never connects: `client` stays `None`, the
listener never starts, its queue is never fed, and `receive()` blocks forever. Outbound limps along,
because `consume()` reconnects on failure — so the failure is **one-directional and quiet**.

Registering in the constructor avoids it with no out-of-band lifecycle call, and is possible because
everything `ConnectionInfo` needs comes from the ClassSpec and the graph, not from materialized data.

### Bonus hazard: synthetic blanknode ids

`DataModel` assigned the id-less blanknode model `id_136553861392864` — derived from its memory
address, so it does not survive a restart. Never use one as a `contained_model_id`.

## Decisions this produced

| # | Decision | Record |
|---|---|---|
| 1 | A semantic connector is any connector that registers itself from the graph, realized as a **binding descriptor** over a connector class | ADR 0023 (amends 0016) |
| 2 | Bindings register **at construction**; recognition over ClassSpec + graph | ADR 0023 (amends 0020) |
| 3 | **Static facets cached at wiring time**; formatter reassembles the node | ADR 0023 |
| 4 | Direction = **most restrictive** of `accessMode` × flavour; absent means read-only | ADR 0023 |
| 5 | **Committed value vs locator** is the domain's choice; the middleware is agnostic | ADR 0024 (amends 0014) |
| 6 | Scenario 3 is a locator: **no `inf:hasValue` literals** in instance data | ADR 0024 → #25 |
