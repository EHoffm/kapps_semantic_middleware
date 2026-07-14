# Example Scenarios

One of four contexts in this repo — see `/CONTEXT-MAP.md` at the repo root for the others.

Self-contained, runnable Jupyter notebooks demonstrating Core Middleware end-to-end (see
`examples/docs/adr/0001-self-contained-example-notebooks.md`), plus the
seed-data/ontology-provisioning
logic that makes each one reproducible against a dummy repository rather than production
knowledge-graph state.

## Language

**Scenario**:
One self-contained, runnable demonstration notebook exercising a specific slice of Core
Middleware functionality end-to-end (e.g. Scenario 1: hello-world workflow registration plus
cross-middleware `execute`; Scenario 2: a door resource's open/close workflows and its live
status).
_Avoid_: Example, demo (used loosely elsewhere in this repo's docs; Scenario is the precise
unit — one notebook, one dummy repository, one seed script).

**Dummy user**:
A GraphDB user/repository dedicated to exactly one Scenario, never shared with production or
with another Scenario, cleared and reseeded on every notebook run.

**Seed step**:
The notebook cells, run before any Scenario logic, that clear the dummy repository entirely
and then insert exactly the ontology this Scenario needs: the relevant Core subset, the `svc:`
module, and the Scenario's own domain ontology — including whatever pre-authored Capability/
Workflow/Service classes and SHACL shapes Core Middleware's ontology-as-ground-truth policy
requires before any `SemanticMiddleware` instance in the Scenario can start.
