# Parameter nodes are skolemized anonymous nodes, so static-facet caching retires

The anonymous node behind a parameter gets a Skolem IRI from the OGM. This happens when it is first persisted or first touched. The node stays anonymous in every other respect. It has no `rdf:type`, no class, no annotation, and no appearance in the served datamodel. Because the node is then addressable, a write touches only the properties that changed. This removes the reason ADR 0023 cached static facets at wiring time.

## Why

A parameter node is a dependent entity. It is meaningless apart from the property that carries it. It holds state that outlives a single write. It needs to be pointed at from outside. RDF's blank node expresses the first half and withholds the second. It is an existential variable. It has no extent, cannot be addressed, and can only be re-found through a pattern match from a named subject. That last property is what makes the current write path destructive. It deletes what it matched and creates a replacement. This orphans the connection metadata the ClassSpec never declared.

[RDF 1.1 Concepts §3.5](https://www.w3.org/TR/rdf11-concepts/#section-skolemization) sanctions the replacement. It states its motivation in the terms we need. The transformation "does not appreciably change the meaning of an RDF graph". It "permits the possibility of other graphs subsequently using the Skolem IRIs, which is not possible for blank nodes". PROV qualification (paper R5/R12), SHACL `sh:focusNode` and `sh:targetNode` (R7/R9), and joining a history snapshot to live state (R14) are examples. Each is "other graphs that subsequently use the node". They are structurally impossible against a blank node. The paper claims all three as satisfied requirements.

The meaning-preservation guarantee is conditional. This is why the OGM must assert **nothing** about the node beyond replacing its label. A `rdf:type inf:MQTTParameter` would be convenient. It would break the guarantee. It would make the node fetchable as a standalone individual. It would give the ontology engineer an axiom to defend for no gain.

The alternative of keeping blank nodes and preserving their labels in Python was rejected. It fixes the orphaning without making the node addressable. The requirements above stay unsatisfiable. Naming the node in the domain ontology was rejected. It pushes naming onto twenty domain engineers. It abandons a pattern locked across the circular factory. Full details and the rejected whole-group-replacement option are in the PRD.

## Consequences

- **The projection is unchanged.** The IRI is carried out of band on the materialized model (a pydantic `PrivateAttr`). It is verified absent from `model_dump()`, `model_dump_json()` and the JSON schema. The attribute still serializes as the same dict of declared properties with no `id`.
- **ADR 0023's static facets retire.** Caching `tu:hasUnit` at wiring time existed only because the write replaced the whole node. Reassembling it into every inbound payload also existed for that reason. With a per-property write, an unchanged facet appears on neither side of the diff. The rest of ADR 0023 is untouched. This includes binding descriptors, registration at construction, and direction from `accessMode` × flavour.

  **Amended 2026-07-29, on building #40: they retire for the graph, not for the model.** This consequence addressed one of two mechanisms and treated it as both. The graph half is genuinely gone, exactly as recorded. The in-memory half is not. `update_persistence_with_value` still does `setattr(contained_model, field_id, value)`. It replaces the whole parameter node in the *persistence model that is served over REST*. `Formatter.deserialize` still receives only the payload with no access to the current value. A bare inbound scalar therefore still blanks the unit and the access mode northbound. Nothing about skolemization touches that path, because it never reaches the store. So `MQTTParameterFormatter` reassembles the node from the facets the binding already read. It is a pure function per message. It reads no current state. This is what the original objection was about. Retire it for real when a formatter can see the value it replaces.
- **ADR 0024's committed-value pattern is unblocked.** Its warning that committing a parameter orphans its connection metadata was the same defect. It can be lifted when the OGM change lands.
- Domain experts keep authoring `[ … ]`. Authored Turtle is never rewritten. A `genid` IRI must never be hand-authored. Store and file then differ in form, never in meaning.
- The minting authority for Skolem IRIs is an ontology-governance decision (Ratan). The IRIs become globally visible. They bind the CI/CD pipeline and the federation outlook in the paper's §7.
- Depends on `SAWeindel/kapps_ogm#4`. It also depends on `kapps_triplestore_interface` rendering a blank node. That node appears on both sides of an update as one variable.

Resolves part of wayfinder ticket #52 under map #24. See `docs/prd/kapps-ogm-anonymous-node-identity.md` requirements R1–R6 and R12.
