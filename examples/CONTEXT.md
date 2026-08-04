# Example Scenarios

One of four contexts in this repo — see `/CONTEXT-MAP.md` at the repo root for the others.

Self-contained, runnable Jupyter notebooks demonstrate Core Middleware end-to-end (see
`examples/docs/adr/0001-self-contained-example-notebooks.md`). Seed-data/ontology-provisioning
logic makes each one reproducible against a dummy repository, rather than production
knowledge-graph state.

## Language

**Scenario**:
One self-contained, runnable demonstration notebook exercises a specific slice of Core
Middleware functionality end-to-end. It is paired with a plain-Python `.py` equivalent better suited
to a debugger — the numbered `step_N_*` functions are the breakpoints. The three scenarios
deliberately show *three different* interaction patterns:

- **Scenario 1** (hello-world) — the **operation-coordination** pattern. A planner dispatches
  an operation through the event trigger and the resource pulls-and-runs it (ADR 0009/0010).
- **Scenario 2** (a door + a minimal mobile robot) — the **direct workflow/state invocation**
  pattern. The robot discovers the door purely through the knowledge graph (SPARQL). It reads
  the door's live status over the StateProperty GET endpoint. It invokes the open workflow of
  the door directly, at the endpoint it found. The door has no operation queue and executes
  synchronously. Not operation based.
- **Scenario 3** (a TransferUnit + a mock PLC) — the **ontology-driven wiring** pattern. No
  topic and no broker address appears anywhere in the scenario code. The middleware reads the
  instance out of the graph. It recognizes which properties are interface-accessible parameters.
  It builds the connectors from the metadata it finds there (ADR 0023). Also the first
  scenario with a **device** end. `mock_transferunit.py` speaks MQTT and knows nothing about
  the graph, the ontology, or the middleware. That is the asymmetry it exists to show. Needs an
  MQTT broker as well as GraphDB. It starts a pure-Python one if none listens.

_Avoid_: Example, demo (used loosely elsewhere in this repo docs). Scenario is the precise
unit — one notebook, one dummy repository, one seed script.

**Dummy user**:
A GraphDB user/repository dedicated to exactly one Scenario, never shared with production or
with another Scenario, cleared and reseeded on every notebook run.

**Seed step**:
The notebook cells run before any Scenario logic. They clear the dummy repository entirely.
Then they insert exactly the ontology this Scenario needs: the relevant Core subset, the `svc:`
module, and the Scenario's own domain ontology. This includes whatever pre-authored
Capability/Workflow/Service classes the Core Middleware ontology-as-ground-truth policy
requires. Only after that can any `SemanticMiddleware` instance in the Scenario start.
