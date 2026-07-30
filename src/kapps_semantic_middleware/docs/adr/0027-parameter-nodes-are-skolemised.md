# Parameter nodes are skolemised anonymous nodes, so static-facet caching retires

The anonymous node behind a parameter gets a Skolem IRI from the OGM when it is first persisted or
first touched, and stays anonymous in every other respect — no `rdf:type`, no class, no annotation, and
no appearance in the served datamodel. Because the node is then addressable, a write touches only the
properties that changed, which removes the reason ADR 0023 cached static facets at wiring time.

## Why

A parameter node is a dependent entity: meaningless apart from the property that carries it, but
holding state that outlives a single write and needing to be pointed at from outside. RDF's blank node
expresses the first half and withholds the second — it is an existential variable, so it has no extent,
cannot be addressed, and can only be re-found by matching a pattern from a named subject. That last
property is what makes the current write path destructive: it deletes what it matched and creates a
replacement, orphaning the connection metadata the ClassSpec never declared.

[RDF 1.1 Concepts §3.5](https://www.w3.org/TR/rdf11-concepts/#section-skolemization) sanctions the
replacement and states its motivation in the terms we need: the transformation "does not appreciably
change the meaning of an RDF graph", and it "permits the possibility of other graphs subsequently using
the Skolem IRIs, which is not possible for blank nodes". PROV qualification (paper R5/R12), SHACL
`sh:focusNode` and `sh:targetNode` (R7/R9), and joining a history snapshot to live state (R14) are all
"other graphs subsequently using the node". They are structurally impossible against a blank node, and
the paper claims all three as satisfied requirements.

The meaning-preservation guarantee is conditional, which is why the OGM must assert **nothing** about
the node beyond replacing its label. A `rdf:type inf:MQTTParameter` would be convenient and would break
the guarantee, make the node fetchable as a standalone individual, and give the ontology engineer an
axiom to defend for no gain.

The alternative of keeping blank nodes and preserving their labels in Python was rejected because it
fixes the orphaning without making the node addressable, so the requirements above stay unsatisfiable.
Naming the node in the domain ontology was rejected because it pushes naming onto twenty domain
engineers and abandons a pattern locked across the circular factory. Full details and the rejected
whole-group-replacement option are in the PRD.

## Consequences

- **The projection is unchanged.** The IRI is carried out of band on the materialised model
  (a pydantic `PrivateAttr`), verified absent from `model_dump()`, `model_dump_json()` and the JSON
  schema, so the attribute still serialises as the same dict of declared properties with no `id`.
- **ADR 0023's static facets retire.** Caching `tu:hasUnit` at wiring time and reassembling it into
  every inbound payload existed only because the write replaced the whole node. With a per-property
  write, an unchanged facet appears on neither side of the diff. The rest of ADR 0023 — binding
  descriptors, registration at construction, direction from `accessMode` × flavour — is untouched.

  **Amended 2026-07-29, on building #40: they retire for the graph, not for the model.** This
  consequence addressed one of two mechanisms and treated it as both. The graph half is genuinely
  gone, exactly as recorded. The in-memory half is not: `update_persistence_with_value` still does
  `setattr(contained_model, field_id, value)`, replacing the whole parameter node in the *persistence
  model that is served over REST*, and `Formatter.deserialize` still receives only the payload with no
  access to the current value. A bare inbound scalar therefore still blanks the unit and the access
  mode northbound — nothing about skolemisation touches that path, because it never reaches the store.
  So `MQTTParameterFormatter` reassembles the node from the facets the binding already read. It is a
  pure function per message and reads no current state, which is what the original objection was
  about. Retire it for real when a formatter can see the value it is replacing.
- **ADR 0024's committed-value pattern is unblocked.** Its warning that committing a parameter orphans
  its connection metadata was the same defect; it can be lifted when the OGM change lands.
- Domain experts keep authoring `[ … ]`; authored Turtle is never rewritten, and a `genid` IRI must
  never be hand-authored. Store and file then differ in form, never in meaning.
- The minting authority for Skolem IRIs is an ontology-governance decision (Ratan), because the IRIs
  become globally visible and bind the CI/CD pipeline and the federation outlook in the paper's §7.
- Depends on `SAWeindel/kapps_ogm#4` and on `graph_db_interface` rendering a blank node that appears on
  both sides of an update as one variable.

Resolves part of wayfinder ticket #52 under map #24. See `docs/prd/kapps-ogm-anonymous-node-identity.md`
requirements R1–R6 and R12.
