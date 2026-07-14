# Capability, Workflow, and Service types must pre-exist; the middleware only creates instances

`@mw.workflow(capability=..., workflow_class=...)` and `@mw.state(capability=...,
state_class=...)` both require IRIs to *already-existing* OWL classes (a Capability subclass,
a Workflow/StateProperty subclass carrying its SHACL shape). `SemanticMiddleware(mode=
"resource", ..., service_class=...)` requires the same for the Service's own type. The
middleware fails at startup if any of these classes are missing. It never mints a class.
What it *does* create automatically, every time, is the corresponding *instance* — one
Capability instance, one Workflow/StateProperty instance, one Service instance per running
process.

**Why**: the alternative — deriving these classes automatically from the decorated Python
function's signature the first time it's seen — was seriously considered and is
architecturally simpler (no upfront ontology-authoring step). It was rejected for a
scale reason specific to this project: a circular factory has hundreds of duplicate
resource instances (many doors, many identical controllers), all of which must share one
`ex:DoorOpenWorkflow` class rather than each middleware process minting its own. Making
classes middleware-derived would mean solving a distributed idempotent class-minting problem
(races between hundreds of processes starting concurrently) for no benefit, since the shape
of a "door open" capability is not something that should vary per physical door anyway — it
is exactly the kind of decision a human ontology engineer should make once, deliberately.
This also keeps the policy uniform across Capability, Workflow, and Service, rather than
having Capability be ground-truth while Workflow is auto-derived (the two were seriously
discussed as asymmetric before settling on uniformity).

**Consequence**: every new physical device type (a new kind of door, a new kind of sensor)
needs its Capability/Workflow/Service/StateProperty classes and SHACL shapes authored in the
ontology *before* its middleware can run — a real bottleneck given this project currently
has one ontology engineer serving twenty domain engineers. See the visual-toolbox PRD
(`docs/prd/visual-toolbox-ontology-authoring-gui.md`) for the planned mitigation.
