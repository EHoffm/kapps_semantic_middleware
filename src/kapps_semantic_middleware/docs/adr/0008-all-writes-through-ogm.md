# All knowledge-graph writes go through the OGM

Every knowledge-graph **write** in this project goes through `kapps_ogm.OGM`
(`OGM.create` for new typed individuals, `OGM.commit` for adding/removing/replacing
properties). No write issues raw SPARQL UPDATE or calls the `graph_db_interface`
mutation methods directly. **Reads** may use the access module (`ogm.db`) directly —
the architecture permits reads there; only writes are constrained.

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
`resolve` follows `svc:realizedByWorkflow`; `deregister` finds a service's workflows
via `svc:isWorkflowOf`. A deployment with OWL reasoning enabled recovers the inverses
automatically; a reasoning-free store simply has one direction, which is sufficient
for this project's own read paths. `cfc:hasCapability` (Resource→Capability, no
inverse in Core, multi-valued) is likewise not materialized in v1 — it is not on any
read path here; adding it would be the one place needing an append and is deferred.
