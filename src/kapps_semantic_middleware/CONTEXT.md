# Core Middleware

One of four contexts in this repo — see `/CONTEXT-MAP.md` at the repo root for the others
(SHACL Interop, Example Scenarios, Module Requirements).

The reference implementation of the KAPPS architecture's Semantic Middleware Runtime: the
Interface-Layer component that lets a piece of Python code running on or next to a shopfloor
resource (or as a standalone service) expose functionality through the knowledge graph, and
lets other middleware instances discover and invoke that functionality via the graph rather
than via hardcoded network references. This context owns the Service/Workflow/Capability/
Operation/Mode registration and execution machinery; it delegates the actual generation and
parsing of workflow precondition/outcome SHACL shapes to the SHACL Interop context.

Built on `aas_middleware` (forked by inheritance, being incrementally reimplemented locally),
`kapps_ogm` (all knowledge graph reads/writes), and `graph_db_interface` (raw triple store
access, used directly where `kapps_ogm` has no equivalent yet, e.g. instance discovery).

## Language

**Service**:
A distributed runtime entity wrapped by a single middleware instance (e.g. a door
controller, a screwing-resource controller, a planning service). Typed via a
domain-specific subclass of `svc:Service` that must pre-exist in the ontology.
_Avoid_: Middleware instance (that's the Python object; Service is its graph representation), Resource (Service *wraps* a Resource, it isn't one).

**Workflow**:
An invokable function exposed by a Service, registered with `@mw.workflow(...)`. Realizes
exactly one Capability. Typed via a domain-specific subclass of `svc:Workflow` that must
pre-exist in the ontology, carrying a SHACL shape describing its arguments (precondition)
and return value (outcome) — see the SHACL Interop context for how that shape is read/
written.
_Avoid_: Skill, Action (AAS-tradition terms for the same invocation-interface idea; KAPPS
reserves "Service" for the deployable middleware-wrapped entity and "Workflow" for what it
exposes — see the paper's explicit divergence from the AAS capability-skill-service model).

**StateProperty**:
A readable, potentially high-frequency-changing property of a Resource, registered with
`@mw.state(...)`. Exposed via a GET-only endpoint backed by an in-memory value; the value
itself is never persisted to the graph — only one stable endpoint triple is written at
registration time. Also typed via a pre-existing domain-specific subclass.
_Avoid_: Sensor value, Observation (those describe the data; StateProperty describes the
graph-exposed access point to it).

**Capability**:
Defined in Core (`cfc:Capability`, subclasses `EquippedCapability`/`FlexibilityCapability`/
`ChangeabilityCapability`). An ability a Resource currently has. In this project's usage,
every Capability instance is created automatically by the middleware from a pre-existing
Capability *type* the moment a matching Workflow or StateProperty is registered — it is
never instantiated by hand.
_Avoid_: Skill (AAS term for a related but not identical concept).

**Operation**:
Defined in Core (`cfc:Operation`, subclass of `Task`). The executable, resource-assigned
form of a task; links to a Capability via `cfc:implementsCapability`. In this project,
resolving and invoking an Operation is what `execute()` does, and the Operation is where the
outcome of that invocation gets recorded afterward.
_Avoid_: Workflow invocation, Job (Operation is the graph-level unit of work; a single
Operation resolves to exactly one Workflow invocation via its Capability).

**Resource**:
Defined in Core (`cfc:Resource`). The physical or logical thing a Service wraps (a door, a
transformer cell, a screwing tool). Required at construction time in resource mode.

**Mode**:
A `SemanticMiddleware` construction-time choice governing what the instance is *for*:
- `"resource"` — wraps one Resource; user-registered Workflows/StateProperties are the REST
  surface; `execute`/CRUD are plain Python methods, not REST-exposed.
- `"server"` — wraps no Resource; CRUD/`execute` themselves are the REST surface (e.g. a
  future data-serving "product server"). Not yet implemented.
- `"watchdog"` — wraps no Resource, exposes little to no REST surface; runs a sweep loop
  that removes stale `svc:address`/`svc:endpoint` triples left by resource-mode instances
  that stopped heartbeating.
_Avoid_: Deployment type, Role (Mode is specifically the constructor discriminator).

**Heartbeat**:
A resource-mode Service's periodic re-assertion of its own liveness — refreshing
`svc:lastHeartbeat` on its Service individual via an internal interval-based Workflow. Read
by watchdog-mode instances to decide staleness.

**Address vs. Endpoint**:
`svc:address` is a Service's base URL, set on startup and removed on
deregistration/staleness. `svc:endpoint` is the full, directly callable URL for one specific
Workflow or StateProperty, also set on startup and removed on deregistration/staleness. Both
being present is a deliberate divergence from the paper's literal "address on Service only"
wording — see
`src/kapps_semantic_middleware/docs/adr/0004-endpoint-on-service-and-workflow.md`.
_Avoid_: URL, endpoint URL used interchangeably for both — they are distinct properties on
distinct entity types.

**KnowledgeGraphConnector**:
An `aas_middleware`-protocol `Connector` (`connect`/`disconnect`/`provide`/`consume`) whose
`provide`/`consume` wrap `kapps_ogm.OGM.fetch`/`commit`. The mechanism by which any
`aas_middleware` construct (workflows, synced connectors) can read/write the knowledge graph
without going around the OGM's validated write path. See
`src/kapps_semantic_middleware/docs/adr/0006-knowledge-graph-connector.md`.

**Deregistration**:
The reverse of registration: on shutdown (or, for watchdog-mode-detected staleness), removing
a Service's `svc:address` and its Workflows'/StateProperties' `svc:endpoint` triples while
preserving the individuals themselves, for provenance.
