# Operation resolves to a Workflow through Capability, not directly

An Operation never references a Workflow directly. Resolution always goes
`cfc:Operation --implementsCapability--> cfc:Capability --svc:realizedByWorkflow--> svc:Workflow`.
`execute()` performs this two-hop lookup, reads the resolved Workflow's `svc:endpoint`, and
invokes it.

**Why**: this was a genuine fork, not an obvious choice. A direct `Operation -> Workflow`
property would be simpler to write and query, and one reading of the paper's §4.3 prose
("an operation... materializes a task-capability match by referencing a concrete workflow
individual") could be taken to license exactly that. But Core's actual, live
`cfc:implementsCapability` property already links `Operation` to `Capability`, not to
anything workflow-shaped — and the paper's own verb for the other half of the chain
("each workflow *realizes* one operational capability") names the relationship this ADR's
`svc:realizedByWorkflow`/`svc:realizesCapability` pair is built to express. Reading §4.3 as
loose prose describing the end-to-end resolution *process* (find the capability, then the
concrete workflow that satisfies it) rather than a literal second RDF property keeps the
design consistent with Core as it actually exists, at the cost of one extra hop on every
resolution.

**Consequence**: every Workflow needs a matching Capability instance before it is reachable
from an Operation — see
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md` for how
that instance comes to exist. This also means a
Capability, not a Workflow, is the unit planning services discover against ("find a service
providing X capability"), matching the paper's framing of planning as capability-driven.

---

**Amendment (2026-07-17, event trigger model).** The resolution chain in this ADR still holds
unchanged — an Operation still resolves `implementsCapability → realizedByWorkflow`. What
changed is what happens *after* resolution: `execute()` no longer performs a synchronous HTTP
POST to the resolved Workflow endpoint and blocks on the result. Under the event trigger model (ADR
0009), resolution locates the **receiving Service** to notify. The caller then triggers that
Service's `execute()`, and the work is pulled from a queue. The two-hop capability
resolution is the discovery step. Invocation is the event trigger.
