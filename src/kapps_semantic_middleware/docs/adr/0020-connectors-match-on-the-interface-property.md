# A connector matches on the interface property hierarchy, and the registry is built from connector classes

A **semantic connector** is a Python class that carries the ontology terms it serves: the
**interface property** it binds to, and the **connection-metadata properties** its protocol needs.
The **connector registry** is assembled at middleware initialization from the list of known, tested
connectors shipped in the middleware, and can be extended programmatically after init with a
domain-built connector class plus its ontology description.

Recognition runs over the materialized datamodel, per attribute: is it a `COMPLEX` property, and is
that property a **subproperty of** some registered connector's interface property?

```python
class MQTTConnector(SemanticConnector):
    interface_property   = INF.isInterfaceAccessibleMQTTParameter
    connection_metadata  = [INF.hasMQTTTopic, INF.hasMQTTBrokerIP,
                            INF.hasMQTTSetTopic, INF.hasMQTTValuePath]
```

```sparql
ASK { tu:hasConveyorSpeed rdfs:subPropertyOf* inf:isInterfaceAccessibleMQTTParameter }
```

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

## Consequences

- ADR 0016's "registry keyed on `rdf:type`" is amended to "keyed on the interface property,
  matched through `rdfs:subPropertyOf*`". The interface-class↔connector pairing, the MQTT contract
  and the `provide`/`consume` semantics are unchanged.
- Recognition needs one TBox query per distinct complex property (batchable), not per instance.
- A domain expert can register a custom connector after init by supplying the class and its ontology
  terms — the row-3 auto-provision case (#35) becomes a matter of *when* registration happens, not
  whether it is possible.
- The consolidation (#39) must keep the interface-property hierarchy under the `inf:` name and must
  declare every connection-metadata property in the parameter property's range restriction, or the
  metadata is dropped before any connector sees it.
- Amends ADR 0016. Depends on root ADR 0002 for the restriction to be extensible at all.

Resolves part of wayfinder ticket #29 under map #24.
