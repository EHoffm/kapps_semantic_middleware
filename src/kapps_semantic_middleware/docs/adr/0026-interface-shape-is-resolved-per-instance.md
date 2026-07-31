# A parameter's interface shape is resolved per instance, and no domain ontology names a protocol

The effective shape of a parameter node is the **union** of its domain range restriction and the
restrictions of every protocol interface resolved for *that node*. The interface half is resolved at
runtime from three sources — ABox evidence, embedding code, and an optional `rdfs:subPropertyOf`
marker — and a domain ontology never has to name a protocol. Which view a consumer sees is decided by
**how far up the interface hierarchy the merge goes**.

## Why

### The protocol is not a type-level fact

ADR 0015 and ADR 0023 both assumed a parameter's protocol is known when the ontology is written. Two
ordinary cases break that:

- **Own-built hardware.** The protocol is not decided when the domain ontology is deployed. It is
  chosen later, per deployment.
- **Two machines of one class, different protocols.** One conveyor speaks MQTT, its twin speaks
  OPC UA. There is no type-level statement that is true of both.

Under the Open World Assumption neither case needs a type-level statement. A class description is
deliberately incomplete, and instance facts complete it differently per instance. Adding a triple the
ontology never anticipated is monotonic and legal. That is the same tolerance the read path already
extends to undeclared properties.

Bought hardware is the opposite case — the supplier fixes the protocol — so the `rdfs:subPropertyOf`
marker stays legal, as documentation of intent and as an optimisation. It is never a precondition.

### The union is an entailment, not a convention

`belt tu:hasConveyorSpeed _:b` plus `tu:hasConveyorSpeed rdfs:subPropertyOf inf:isInterfaceAccessibleMQTTParameter`
entails `belt inf:isInterfaceAccessibleMQTTParameter _:b` (rdfs7), and with a range on that
superproperty, `_:b rdf:type C_mqtt` (rdfs3) — alongside `_:b rdf:type C_speed` from the domain range.
The node *is* an instance of the intersection. The OGM computing that union implements the entailment
rather than inventing an atomicity rule of its own, which matters because the alternative — declaring
that everything on the node is one atomic block — has no basis in the ontology and would not survive
review.

### Union, not precedence

A node carrying both `inf:hasMQTTTopic` and an OPC UA node id is not contradictory. It describes a
dual-homed device. So every resolved interface is merged and the connector registry decides what is
actually wired, which it already does (ADR 0020, ADR 0023) under `autoregister_connectors` and the
instance's flavour (ADR 0022). Embedding code may mark its declaration **authoritative**, which
selects the shape and drives write-back removal of stale metadata — the only way to migrate a machine
from one protocol to another without hand-deleting triples. Two different broker addresses on one node
remain a data error, and no precedence rule should paper over it.

### Views are merge depth

The interface hierarchy is ordered by northbound-safety, so the projection needs no filtering step:

| View | Merges | Contains |
|---|---|---|
| user (northbound REST) | domain restriction + `inf:isInterfaceAccessibleParameter` | value, unit, access mode |
| wiring (connector registry) | the above + `inf:isInterfaceAccessible<Protocol>Parameter` | + topic, set topic, broker |

A broker address is physically absent from the served model — the restriction *is* the projection.
This retires the middleware-side filtering that ADR 0028 proposed and that `#51` closed unbuilt, and it
keeps ADR 0018's principle intact: a view belongs to its consumer.

## Consequences

- **`inf:` gains real `rdfs:range` restrictions on both marker properties**, and their split is a
  hard authoring constraint: northbound-safe content (`inf:accessMode`) on the parent property,
  protocol connection details on the protocol subproperty. Ratan owns this.
- **`examples/transferunit.ttl` drops `inf:accessMode` from its restrictions** — it now arrives from
  `inf:isInterfaceAccessibleParameter` — and its `rdfs:subPropertyOf` markers become optional.
- The effective ClassSpec is **instance-dependent**, so any spec cache must be keyed on
  `(class, scope, resolved interfaces)`, not `(class, scope)`.
- Depends on `kapps_ogm` merging anonymous restriction ranges instead of raising on arity
  (`SAWeindel/kapps_ogm#1`, root ADR 0002), extended to walk `rdfs:subPropertyOf*`.
- ADR 0015's row 3 (auto-provision) is answered: the embedding-code source supplies the shape for the
  first write, and the write-back rule persists it, after which ABox evidence carries the node.
- Amends ADR 0023 and ADR 0020: recognition may now drive *specification*, not only wiring.

Resolves wayfinder ticket #52 under map #24. See `docs/prd/kapps-ogm-anonymous-node-identity.md`
requirements R7–R9.
