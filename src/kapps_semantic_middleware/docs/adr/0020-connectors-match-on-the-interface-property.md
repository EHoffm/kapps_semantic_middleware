# A connector matches on the interface property hierarchy, and the registry is built from connector classes

A **semantic connector** is a Python class that carries the ontology terms it serves: the
**interface property** it binds to, and the **connection-metadata properties** its protocol needs.
The **connector registry** is assembled at middleware initialization from the list of known, tested
connectors shipped in the middleware, and can be extended programmatically after init with a
domain-built connector class plus its ontology description.

Recognition runs per complex property: is it a `COMPLEX` property, and is that property a **subproperty
of** some registered connector's interface property?

> **Amended 2026-07-27 (#28, ADR 0023).** Recognition runs over the **ClassSpec and the graph at
> construction**, not over the materialized datamodel as originally written. Everything it needs — which
> properties are COMPLEX, which match an interface property, which component individuals exist — is
> available without instance data, and registering this early is what lets `lifespan` connect the
> connectors at all. A connector registered during `on_start_up` never has `connect()` called and its
> inbound traffic dies silently. The disposition rules below are unchanged.

```python
class MQTTConnector(SemanticConnector):
    interface_property   = INF.isInterfaceAccessibleMQTTParameter
    connection_metadata  = [INF.hasMQTTTopic, INF.hasMQTTBrokerIP,
                            INF.hasMQTTSetTopic, INF.hasMQTTValuePath]
```

```sparql
ASK { tu:hasConveyorSpeed rdfs:subPropertyOf* inf:isInterfaceAccessibleMQTTParameter }
```

Whether recognised parameters are actually *wired* is controlled at construction by
**`autoregister_connectors`**, and how they are wired by **`connector_sync_direction`**, which is
handed straight to `aas_middleware`'s `add_synced_connector`:

```python
SemanticMiddleware(mode="resource", resource_iri=tui.TransferUnit1, …,
                   autoregister_connectors=True,
                   connector_sync_direction=SyncDirection.TO_PERSISTENCE)
```

| flavour | setting | behaviour |
|---|---|---|
| controller | `True`, `BIDIRECTIONAL` (default) | reads live values and drives the device |
| monitor | `True`, `TO_PERSISTENCE` | reads live values, can never drive the device |
| inspector | `False` | nothing connected; structure and graph content only |

**Recognition and the projection run in all three.** The flag gates wiring, never recognition — see
below.

## Why

### The blanknode has no class to match on

ADR 0016 speaks of an **interface class** resolved by `rdf:type`. Checked against the live graph
(#29), the parameter blanknode carries **no named type at all**: its only `rdf:type` values are the
anonymous `owl:Restriction` nodes of the property's range, they exist solely under inference, and
`_fetch_complex_property` queries `FROM <http://www.ontotext.com/explicit>`, so they are not even
fetched. Matching on a blanknode class would require every domain engineer to type every parameter
node explicitly, *and* the restriction to declare `rdf:type`, or materialization would drop it.

The binding is already expressed upstream, on the property:

```
tu:hasConveyorSpeed  rdfs:subPropertyOf  inf:isInterfaceAccessibleMQTTParameter
                     rdfs:subPropertyOf  inf:isInterfaceAccessibleParameter
                     rdfs:subPropertyOf  inf:isAttribute
```

Matching there works today against real instance data and asks nothing new of domain engineers.

### The connector owns its vocabulary; the core owns none

The core must not hardcode domain IRIs, and a connector may hardcode only terms from its own
ontology (ADR 0021). Putting the interface property and the metadata list *in the connector class*
satisfies both: the core holds a registry of opaque entries and asks it questions, and the MQTT
vocabulary exists in exactly one place — the MQTT connector. A new protocol is a new class plus its
ontology description, registered the same way, with no core change. That is ADR 0016's
protocol-extensibility seam, relocated from the ontology to the pairing and made concrete.

### Recognition, not a whitelist

The alternative was for the core to hold a list of user-facing properties and drop everything else.
Rejected: publishing a new user-facing property would then be a core change, putting the single
ontology engineer back on the critical path of twenty domain engineers (ADR 0003's constraint).
Under recognition, the core's list is empty and stays empty.

### Unrecognised content is data, not an error

A complex property that matches no registered connector is **not** a failure and **not** a parameter.
The user put it in their ClassScope, so they asked for it: a manufacturer, a serial number, a
material. It is displayed and readable as ordinary datamodel content, and nothing is registered, no
get/set workflow is mounted, no connector is wired. The same holds for properties on a recognised
parameter's blanknode that correlate to nothing in the connector framework — left alone, shown as
regular data of the complex property.

This is what makes the projection safe to state simply: **hide what a connector claims, show
everything else.** A view that asked for a parameter never asked for its transport details, because
a ClassScope cannot reach them (ADR 0019); a view that asked for a manufacturer asked for exactly
what it got.

### A resolved connector missing its metadata is loud

If a property matches a registered connector's interface property but the materialized blanknode
lacks a property that connector declares it needs, the wiring has silently failed — the value would
never flow and the resource would come up dead. This is reported loudly, naming the missing property
and the restriction that failed to declare it, because the cause is almost always that the parameter
property's `rdfs:range` restriction does not declare the metadata the instance asserts, and the drop
is otherwise a single `NodeValidator` warning.

Blanket `strict=True` on `NodeValidator` is **not** available as a substitute: the authoritative
upstream instance data puts `rdfs:comment` on its parameter blanknodes, which no restriction
declares, so strict validation fails on ground truth.

### The wiring flag must not gate recognition

Two middleware instances may be bound to the same graph entity — a controller that drives it and a
read-only monitor beside it. The monitor must not open a write path to the device, hence
`autoregister_connectors` / `connector_sync_direction`.

It is tempting to implement "no connectors" as "no registry". That would be a **security hole**: with
nothing registered, no property is recognised as a parameter, so by the rule above the blanknode
becomes ordinary data and is **shown** — and the read-only monitor would serve `inf:hasMQTTTopic` and
`inf:hasMQTTBrokerIP` northbound, which is exactly the bypass ADR 0018/0019 exist to prevent. The
least-privileged instance would leak the most.

So the registry is **always** built and recognition **always** runs. The flag skips `connect()` and
the sync registration only. The projection's behaviour is identical in all three flavours, and the
security property is independent of how the instance is configured.

### Direction is the framework's concept, not ours

`aas_middleware` is production-ready and already models this: `add_synced_connector` takes
`sync_role` (`GROUND_TRUTH`/`READ_ONLY`/`READ_WRITE`/`WRITE_ONLY`) and `sync_direction`
(`TO_PERSISTENCE`/`FROM_PERSISTENCE`/`BIDIRECTIONAL`), and `lifespan` connects everything in the
connection registry. A monitor is `TO_PERSISTENCE` — the device's values flow into persistence and
nothing flows back out to the device. Inventing a parallel read-only notion would duplicate a
mechanism that already works, so we pass the framework's vocabulary through rather than wrap it.
Core paradigms change only where the semantic layer genuinely needs something the framework lacks.

## Consequences

- ADR 0016's "registry keyed on `rdf:type`" is amended to "keyed on the interface property,
  matched through `rdfs:subPropertyOf*`". The interface-class↔connector pairing, the MQTT contract
  and the `provide`/`consume` semantics are unchanged.
- Recognition needs one TBox query per distinct complex property (batchable), not per instance.
- A domain expert can register a custom connector after init by supplying the class and its ontology
  terms — the row-3 auto-provision case (#35) becomes a matter of *when* registration happens, not
  whether it is possible.
- `autoregister_connectors` and `connector_sync_direction` are constructor parameters of resource
  mode, defaulting to `True` / `BIDIRECTIONAL` so existing scenarios are unaffected.
- Controller, monitor and inspector are **configurations of one library**, not three classes. Running
  two instances against one resource also needs distinct service identities — ADR 0022.
- The consolidation (#39) must keep the interface-property hierarchy under the `inf:` name and must
  declare every connection-metadata property in the parameter property's range restriction, or the
  metadata is dropped before any connector sees it.
- Amends ADR 0016. Depends on root ADR 0002 for the restriction to be extensible at all.

Resolves part of wayfinder ticket #29 under map #24.
