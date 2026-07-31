# All knowledge-graph writes go through the OGM

Every knowledge-graph **write** in this project goes through `kapps_ogm.OGM`
(`OGM.create` for new typed individuals, `OGM.commit` for adding/removing/replacing
properties). No write issues raw SPARQL UPDATE or calls the `graph_db_interface`
mutation methods directly. **Reads** may use the access module (`ogm.db`) directly —
the architecture permits reads there. Only writes are constrained.

**Why**: the paper's central architectural commitment is that "every write
originates as an OGM commit... making the OGM the architecture's single validated
write path" (§4.4.2). An earlier iteration of this project violated that: `registration.py`
wrote structural triples directly via `graph_db_interface` (`triples_add`,
`triple_add`, SPARQL `DELETE WHERE`), and the `KnowledgeGraphConnector` (ADR 0006)
was never wired in — so no write went through the OGM at all. That was a fidelity
shortcut, corrected here.

Realizing it required fixing three latent defects in `kapps_ogm`'s commit path
(a `datetime` serialization crash, `from_node_data` dropping empty-valued keys so
removal was impossible, and `commit` requiring equal-length diffs) and generalizing
`graph_db_interface.triples_update` to a single **atomic** `DELETE/INSERT`
transaction. The atomicity is not incidental: a replacement of a cardinality-
constrained property — e.g. a possession handover under a "possessed by exactly one
resource" SHACL shape — must apply the removal and the insertion in one transaction,
or the intermediate (zero-possessor) state fails validation.

**Consequence — one direction of each inverse is materialized.** Because
`OGM.create` writes a single instance's own properties, and appending to a growing
multi-valued container property (e.g. a Service's `svc:hasWorkflow` as each workflow
registers) would require a read-modify-write, we materialize only the direction
owned by the newly-created instance: a Service's `svc:isServiceOf`, a Workflow's
`svc:isWorkflowOf` and `svc:endpoint`, a Capability's `svc:realizedByWorkflow`, a
StateProperty's `svc:isStatePropertyOf`. The container-side inverses (`svc:hasWorkflow`,
`svc:hasService`, `cfc:hasCapability`, …) are OWL-inferable and are not written.
Queries in this project therefore use the materialized (instance-owned) direction —
`resolve` follows `svc:realizedByWorkflow`. `deregister` finds a service's workflows
via `svc:isWorkflowOf`. A deployment with OWL reasoning enabled recovers the inverses
automatically. A reasoning-free store simply has one direction, which is sufficient
for this project's own read paths. `cfc:hasCapability` (Resource→Capability, no
inverse in Core, multi-valued) is likewise not materialized in v1 — it is not on any
read path here. Adding it would be the one place needing an append and is deferred.

---

**Amendment (2026-07-21, #17 — Resource→Capability is now materialized).** The deferral above
is lifted for `cfc:hasCapability`. Queue durability (ADR 0009) requires a resource to find its
own Operations by **ontology traversal** — `?op cfc:implementsCapability ?cap . <resource>
cfc:hasCapability ?cap` — rather than by matching IRI names, so `register_workflow` /
`register_state_property` now **do** write `cfc:hasCapability` (Resource→Capability) as each
Capability registers. This is the first container-side inverse this project materializes: it is
written on the pre-existing resource (the only available direction — Core gives `hasCapability`
no inverse), and it is now on a read path (`find_resource_operations`, the watchdog sweep). The
"queries use the materialized instance-owned direction" invariant is thereby relaxed to *queries
traverse whichever ontology link the read needs, and this project materializes the links its
reads traverse* — never identifying entities by IRI name.

**Mechanism note.** `cfc:hasCapability` — like `cfc:implementsCapability` and an Operation's
`rdf:type` in `create_operation`/`revert_operation` — is a **Core** term whose property domains
are not declared in the Core *subset* the scenarios load, so `OGM.create`/`commit` cannot
hydrate it and it is written through the low-level `graph_db_interface` triple API. This is a
bounded, documented exception to the OGM-only write rule, forced by the loaded-subset
limitation. Routing these Core writes through the OGM requires the loaded ontology to declare
the Core Operation/Capability property domains (a `kapps_ogm`/ontology follow-up — see the
`create_operation` docstring).

---

**Amendment (2026-07-22, follow-up — `create_operation` now writes through `OGM.create`).**
Re-checked against the paper (the reference implementation's ground truth): §4.3 states "every
write originates as an OGM commit… making the OGM the architecture's **single validated write
path**," and §4.4.2 locates the validation "at the Python boundary before any SPARQL update is
constructed." So the raw-triple writes above are a **fidelity gap**, not a blessed alternative
path — the `graph_db_interface` is not a service-facing write path. This amendment closes that
gap for **Operation creation**: the loaded scenario/demo ontologies now declare
`cfc:implementsCapability` (`rdfs:domain cfc:Operation`, `rdfs:range cfc:Capability`), so
`create_operation` persists the whole Operation (`rdf:type` + `implementsCapability` +
`svc:operationStatus`) in one `OGM.create`.

**What is *not* yet closed, and why.** Two low-level writes remain, each for a principled reason:

- `cfc:hasCapability` (written at registration, Resource→Capability) is **multi-valued** — a
  resource provides many capabilities. `OGM.commit` has whole-property-set *replace* semantics,
  so routing an append through it would clobber the resource's other capabilities. The correct
  fix is a **validated single-triple append in `kapps_ogm`** (the paper, §4.4.2, explicitly
  envisions the OGM adding/removing individual property assertions). Per ADR 0001 that is a
  `kapps_ogm` enhancement, not an ad-hoc addition here. This is the **same** gap as
  `cfc:hasPossessor` in `switch_possession`/`create_possession` (ADR 0011) — both are
  multi-valued appends parked on `ogm.db.triple_add` awaiting that one capability.
- `revert_operation`/deregister **deletions** stay on `ogm.db.triple_delete`: the OGM
  intentionally offers no entity deletion (paper §4.4.2), and triple-level removal is the
  sanctioned access-module operation for "remove exactly what was written."
