# The architecture has exactly one closed-world moment: SHACL at admission

Everywhere else, the absence of a triple means **unknown**, never **false**. Nothing the OGM derives
from OWL may produce a required field, reject an unknown property, or treat its own view of a node as
that node's full extent. Requiredness, closedness and cardinality *enforcement* are closed-world
statements and belong to SHACL shapes evaluated by the triple store when a write is admitted.

## Why

The paper already states this division (§4.2.2): OWL reasoning enriches under the Open World
Assumption. SHACL "provides closed-world constraint checking over concrete system states" and rejects
updates that violate it. The code does not honour it, in three places, and each one produced a real
defect:

- **`owl:someValuesFrom` becomes a required pydantic field.** `PropertySpec.specify` sets
  `min_count = 1` from `someValuesFrom` (`property_spec.py:495`), `NodeValidator` correctly downgrades
  the shortfall to a warning, and `to_pydantic_field` then turns the same fact into
  `Field(default=...)`. An existential axiom says a value exists *in the world*. It does not say the
  triple is in your graph. Since ADR 0024 removed the value literals from `transferunit.ttl`, this
  predicts that materialising a seeded belt raises `ValidationError: inf-hasValue Field required`.
- **The write path assumes its schema is exhaustive.** It serialises only declared properties and
  replaces whole blank-node groups, so triples the ontology never anticipated are destroyed — while
  the read path deliberately tolerates them. Under OWA a graph may legitimately carry more than any
  schema describes. A write path must not assume otherwise.
- **`extra="forbid"`** in `ClassSpec.to_pydantic_model` (`class_spec.py:104-106`) is assigned after
  `create_model` and is inert — which is why nothing has broken yet. Making it live without a policy
  for undeclared properties would break every fetch of real data, since upstream instance data carries
  undeclared `rdfs:comment`.

The rule is also what makes the ontology safe to author. If OWL restrictions gated writes, every
`someValuesFrom` a domain engineer wrote would become an operational requirement that the shop floor
must satisfy before the middleware will start. Requirements belong in shapes, which are reviewed as
constraints. Descriptions belong in the ontology, which is read as knowledge.

## Consequences

- OWL restrictions supply **type**, never requiredness. `allValuesFrom` is the correct vocabulary for
  typing a parameter's datatype, since it constrains all values instead of asserting one exists.
  `someValuesFrom` remains legal and documents intent, but must not be read as a gate.
- Requiredness arrives with SHACL support (`SAWeindel/kapps_ogm#3`) via `sh:minCount`, at which point a
  shape may legitimately make a field required.
- `examples/transferunit.ttl` changes `inf:hasValue` from `someValuesFrom` to `allValuesFrom`, which
  the locator pattern (ADR 0024) requires anyway: a parameter that has not been observed yet has no
  value triple.
- An empty projection stays legitimate, as already recorded under `#29`.
- This ADR is a general rule, not a scenario-3 decision: it applies to every ontology the middleware
  consumes.

Resolves part of wayfinder ticket #52 under map #24. See `docs/prd/kapps-ogm-anonymous-node-identity.md`
requirement R10.
