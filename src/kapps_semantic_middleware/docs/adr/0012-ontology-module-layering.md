# Ontology-module layering: cfc: (Core) / mes: (MES) / svc: (Service)

Vocabulary lives in three layers, each a separate ontology module:

- **`cfc:` — Core** (`https://w3id.org/circularfactory/Core#`): published, external, superior.
  `Operation`, `Capability`, `Resource`, `Task`. **Imported and specialized, never modified.**
- **`mes:` — MES** (newly minted at `https://w3id.org/circularfactory/MES#`, MES =
  Manufacturing Execution System): a **domain** ontology that `owl:imports` Core and *details it
  out* with manufacturing-execution functionality — **possession** (`mes:hasPossession` /
  `mes:isPossessedBy`) and the **handover-ability** tag (`mes:hasHandoverAbility`) with its six
  enumerated individuals (`Put`/`Receive`/`Pick`/`Release`/`Pass`/`Retrieve`). Domain experts
  touch this layer.
- **`svc:` — Service** (`https://w3id.org/circularfactory/Service#`): middleware-to-middleware
  **reachability and coordination only**, not touched by domain experts. `Service`/`Workflow`/
  `StateProperty`, `address`/`endpoint`/`lastHeartbeat`, the resolution chain, and the
  **Operation status + execution provenance** (ADR 0009) — coordination state, so it belongs
  here and joins the provenance block already present.

The governing principle: **Core is superior; `mes:` extends Core by importing and specializing
it. Whatever is in Core is imported and extended, not duplicated or re-homed.** `mes:` and
`svc:` are sibling modules that both import Core — `mes:` domain-facing, `svc:` middleware-facing.

**Why**: an earlier framing (the #7 resolution) parked possession and handover vocabulary in
`svc:`, which conflates domain manufacturing-execution concepts with pure reachability and drags
domain experts into the middleware's communication vocabulary. Separating them keeps `svc:`
domain-free and gives MES functionality a home the project owns and can evolve. Possession was
placed in `mes:` rather than `cfc:` deliberately: treating "which resource holds a workpiece" as
Core material-flow state would mean **extending the published Core** — the single ontology
engineer's domain, shared across ~20 domain engineers — for what is really execution state; the
project keeps Core minimal and stable and mints its own module instead.

**Consequence**: the handover primitive (ADR 0011) reads/writes the `mes:` predicates while its
*code* stays generic core-middleware machinery — vocabulary is MES-layered, mechanism is core.
Operation-status and provenance vocabulary lives in `svc:` (the folded status machine of ADR
0009). Re-authoring the use-case ontologies onto this stack (UC possession/handover → `mes:`,
Service/Workflow → `svc:`, Operation/Capability → `cfc:`) is downstream in
[#6](https://github.com/EHoffm/kapps_semantic_middleware/issues/6)/Map #2. **Alignment of `mes:`
with an external manufacturing-execution ontology standard is deferred** to a `/research`
sub-task and does not block minting our own module (same posture as importing Core). Promotes the
resolution of [#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10).
