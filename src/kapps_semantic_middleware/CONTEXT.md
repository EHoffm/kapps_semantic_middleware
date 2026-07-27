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

**Parameter** (interface-accessible parameter) — _supersedes StateProperty (ADR 0015)_:
A readable and/or settable state of a Resource, modelled as **one graph node** carrying its
value/unit **and** the metadata a protocol connector needs to reach the device (e.g. an MQTT
topic + broker). Typed by a protocol **interface class** under `inf:InterfaceAccessibleParameter`.
The middleware's former "readable state" and the shop-floor "parameter" are one thing seen from
two directions — southbound (how the middleware reaches the device) and northbound (how peers
reach the middleware). Whether it is externally settable is a **facet** (an access mode), not a
subclass. The live value is never persisted to the graph. Northbound it is **atomic**: value, unit
and access mode are read and written together as one dict, because they share one blanknode — the
locked circular-factory pattern for metadata about a property, RDF having no properties-about-
properties (ADR 0017). Its **shape is the TBox restriction** on its property's `rdfs:range`, not the
instance data: anything the restriction does not declare is dropped at materialization with only a
warning, so metadata a connector needs must be declared there or it never arrives (ADR 0019).
A complex property that matches no registered connector is **not** a Parameter — it is ordinary
data the consumer asked for, displayed and readable, with nothing wired (ADR 0020).
_Avoid_: StateProperty (retired term, ADR 0015); Sensor value / Observation (those describe the
data, not the graph node); Capability (states have none — there is no "light-barrier capability").

**Interface class**:
A protocol-specific parameter class — `inf:MQTTParameter`, `inf:OPCUAParameter`, … under
`inf:InterfaceAccessibleParameter` — that declares what connection metadata its protocol needs and
is paired **one-to-one with a connector** in the middleware. The protocol-extensibility seam: a new
protocol is a new interface class plus a new connector, no core change.
_Avoid_: Adapter, Driver (the interface class is the ontology term; the connector is its runtime pair).

**ClassScope**:
A **projection — a view** — over the graph, expressed (in the OGM) as a tree of property-chains
rooted at a class. A view **belongs to its consumer** and is rooted at the node that consumer cares
about. There is no single "the datamodel" for a resource. This is how one central ontology serves
both the IT-OT boundary and the control/factory layer without duplicating concepts (ADR 0018).
A view **terminates at a Parameter and cannot select within one**: below a complex property the
chain is silently discarded, and the blanknode's contents are fixed by the TBox restriction, the
same for every consumer (ADR 0019). A scope chooses *which* parameters, never *which parts* of one.
An **empty** projection is legitimate — the graph holds the information, and a resource whose view
is a bare individual serves a one-field datamodel and starts normally.
_Avoid_: Filter, Query (a ClassScope is a reusable named view of which metadata to materialise).

**Root** (of a view):
The node a ClassScope is rooted at. Being a root is what makes a Resource a *top-level* thing rather
than a component — TransferUnit1 is a unit and ConveyorBelt1_left is a part of it **because a view is
rooted at the unit and reaches the belt**, not because of any part-of relation in the graph. There is
no composition property in Core, and none is needed.
_Avoid_: Top-level resource, Aggregate (both suggest an intrinsic property of the resource; rootedness
is a property of the view).

**User view**:
The ClassScope a resource-mode middleware is constructed with, and the one it materializes into the
datamodel it REST-exposes: the **northbound** projection. Stated by the domain code that embeds the
library, since only that code knows what the instance is for. Omitting it falls back to an unscoped
fetch, which materializes the `id` alone — a legitimate, if minimal, projection.
Connection metadata is absent from it not because the view declines to fetch it (it cannot — see
**ClassScope**) but because the **Projection** removes it (ADR 0019), so a peer cannot learn the
broker address and bypass the middleware.
_Avoid_: The datamodel, Schema (it is one view among many; a connector's view of the same resource is
a different one).

**Projection** (northbound):
The middleware-side step that removes connection metadata from a materialized Parameter before the
datamodel is REST-exposed. It hides exactly the properties a registered **Semantic connector**
declares for its own protocol, and shows everything else — so unrecognised blanknode content stays
visible as ordinary data, and a new protocol is covered the moment its connector is registered
rather than when someone updates a deny-list (ADR 0019, ADR 0020).
_Avoid_: Filter, Deny-list (the set is declared by connectors, not maintained centrally); View
(the view is the ClassScope; the projection is what the middleware does to what the view returned).

**Interface property**:
The property a **Semantic connector** binds to — `inf:isInterfaceAccessibleMQTTParameter` and its
siblings, under `inf:isInterfaceAccessibleParameter`. A resource's parameter declares its protocol by
being a **subproperty** of one, which is how the authoritative upstream ontology already models it.
Recognition is `rdfs:subPropertyOf*` against the registry; the parameter blanknode itself carries no
named class to match on (ADR 0020).
_Avoid_: Interface class (retained for the ontology concept, but the *match* is on the property).

**Known primitives**:
The bounded form of the system's flexibility: novel *combinations* are handled, novel *vocabulary* is
not. A task assembled from grip/move/place may never have been seen in that combination, and a product
may combine a screw and a gear never before combined — but grip, move, place, screw and gear are all
known. Views and discovery listings are configured over known classes for this reason; it is a
deliberate boundary, not a limitation to be engineered away.
_Avoid_: Zero-configuration, Fully generic (both overclaim — the system does not discover concepts it
has never been taught).

**Semantic connector**:
An aas_middleware `Connector` (`connect`/`disconnect`/`provide`/`consume`) paired with a **protocol
metadata ontology**. The class **carries the ontology terms it serves in its own code**: the
**Interface property** it binds to, and the connection-metadata properties its protocol needs — which
are also exactly what the **Projection** hides northbound. `provide` reads the live value, `consume`
writes it (a read-only Parameter uses `provide` only). A connector may hardcode terms from its own
ontology and no others; domain vocabulary never appears in it, nor anywhere in the core (ADR 0021).
_Avoid_: Connector (the bare aas_middleware protocol, without the metadata ontology); Adapter, Driver.

**Connector registry**:
The universal map from **Interface property** to **Semantic connector**. Built at middleware
initialization from the known, tested connector classes shipped in the middleware, and extensible
after init by injecting a domain-built connector class together with its ontology description.
Resolution is `parameter property rdfs:subPropertyOf* → interface property → semantic connector`;
supporting a new protocol is registering a new entry, never a core change. The seam by which the
middleware ships standard `inf:` connectors (MQTT, OPC-UA reserved) and a domain expert can register
their own (ADR 0020).
_Avoid_: Connector factory, Plugin loader (the registry keys specifically on the interface property);
keying on `rdf:type` (superseded — the parameter blanknode has no named type).

**Capability**:
Defined in Core (`cfc:Capability`, subclasses `EquippedCapability`/`FlexibilityCapability`/
`ChangeabilityCapability`). An ability a Resource currently has. In this project's usage,
every Capability instance is created automatically by the middleware from a pre-existing
Capability *type* the moment a matching Workflow or StateProperty is registered — it is
never instantiated by hand.
_Avoid_: Skill (AAS term for a related but not identical concept).

**Operation**:
Defined in Core (`cfc:Operation`, subclass of `Task`). The executable, resource-assigned
form of a task; links to a Capability via `cfc:implementsCapability`. A caller creates an
Operation in the graph and dispatches it to the resource that will carry it out; that
resource queues it, pulls it, runs it, and the outcome is recorded back onto it. The
graph-level unit of work exchanged between middleware instances.
_Avoid_: Workflow invocation, Job (Operation is the graph-level unit of work; a single
Operation resolves to exactly one Workflow via its Capability).

**Event trigger** (`execute()`):
The receiver-side built-in Workflow that every resource-mode middleware exposes on its REST
API. A caller "triggers" it to signal that an Operation addressed to that resource now exists in
the graph; the receiver enqueues the Operation, `ogm.fetch`es it, and hands it to an optional
domain callback (else leaves it `queued`). The trigger carries only the Operation IRI — the
payload lives in the graph — and does not block on the work or return a business result.
_Avoid_: RPC call, Invoke (the event trigger notifies; it does not run the work synchronously).

**Dispatch**:
The caller-side act of handing an Operation to another resource: create the Operation
individual in the graph (through the OGM-routed write path) and then fire the receiver's
event trigger. Accessed from domain Python as a transaction context manager — the body populates
the Operation, the atomic exit performs the create-and-notify.
_Avoid_: Send, Publish (there is no message bus; dispatch is a graph write plus an event trigger).

**Operation queue**:
A resource-mode middleware's pending-work list — the Operations addressed to its Resource
that await or are in progress. Held in memory as a cache and reconstructed at startup by
querying the graph (own `queued` operations, plus own orphaned `running` operations to
reclaim); filled live by event triggers. A dead resource's stranded operations are swept
centrally by a watchdog, not by per-resource polling.
_Avoid_: Message queue, Broker (there is no broker; the queue is a view over graph state).

**Operation status**:
The lifecycle state of an Operation: `queued` (created and addressed, awaiting pull) →
`running` (pulled, in progress) → `done` or `failed` (terminal). Drives coordination and
recovery. Execution provenance (which Workflow ran it, when, the result) is written as part
of the terminal transition, so the status is itself the provenance record — there is no
separate success flag.

**Pull-and-run**:
The receiver-side transaction context manager by which domain code takes the next `queued`
Operation, sets it `running` (re-fetching it under a domain-supplied `ClassScope`), runs the
work in the body, and on atomic exit records the terminal `done`/`failed` state and
provenance — dumping the Resource's datamodel to the graph on failure.
_Avoid_: Poll, Consume (pull-and-run is the guarded unit of work, not the delivery mechanism).

**Resource**:
Defined in Core (`cfc:Resource`). The physical or logical thing a Service wraps (a door, a
transformer cell, a screwing tool). Required at construction time in resource mode.

**Mode**:
A `SemanticMiddleware` construction-time choice governing what the instance is *for*:
- `"resource"` — wraps one Resource; the REST surface is the user-registered Workflows/
  StateProperties, the built-in `execute()` event trigger, and a CRUD REST API generated from
  the resource's own datamodel (`generate_rest_api_for_data_model`; ADR 0005 #13 amendment). The
  transactional context-manager surface (dispatch/`request`, pull-and-run, handover) and the
  graph-write helpers stay Python-only, not REST-exposed.
- `"server"` — wraps no Resource; CRUD/`execute` themselves are the REST surface (e.g. a
  future data-serving "product server"). Not yet implemented, and deliberately still reserved: a
  graph-*consuming* participant (a planner, a mobile robot, a controller) is a resource-mode
  planner with its own Resource, not a server (ADR 0005, #32 amendment).
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
