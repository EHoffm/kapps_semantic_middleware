# SHACL, not OWL Restrictions, for workflow precondition/outcome

A Workflow's precondition (arguments) and outcome (return value) are represented as a SHACL
`NodeShape` targeting the Workflow's class (`sh:targetClass`, not `sh:targetNode`), built
from the decorated Python function's type hints. This is scaffolding: `kapps_ogm` has no
SHACL support today (confirmed: zero references to SHACL/`ValidationReport`/`sh:` anywhere
in `kapps_ogm` or `kapps_triplestore_interface`), so the generation and parsing logic for these shapes
lives temporarily inside `kapps_semantic_middleware` itself, clearly marked as a stopgap, in
place of the natural long-term home for this logic.

**Why**: the closest prior art, `semantic_service`, used an OWL Restriction pattern
(`owl:Restriction` + `owl:hasValue` chains) that `kapps_ogm`'s `PropertySpec.specify()`
already knows how to parse into typed Pydantic fields via its `COMPLEX` property-type path —
reusing that would have meant zero new read-side code. SHACL was chosen anyway because it is
the mechanism the rest of the KAPPS architecture actually uses for constraint enforcement
(UC2's physical-invariant shapes), and treating workflow signatures the same way is
consistent with where this project is headed, not just where it is today. `kapps_ogm`
gaining native SHACL interpretation is planned as v2 work (see
`docs/prd/kapps-ogm-shacl-support.md`, written alongside this decision) — until then, this
project owns its own read/write logic for these shapes.

Shapes target the Workflow's *class*, not each instance, for the same fleet-scale reason as
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`: hundreds
of doors share one shape, not hundreds of duplicates.

**Consequence**: `kapps_semantic_middleware` currently contains SHACL-generation/parsing
logic that duplicates work properly belonging in `kapps_ogm`. This is a known, intentional,
temporary seam — it should be deleted once `kapps_ogm` absorbs the capability described in
the PRD, not extended further in place.
