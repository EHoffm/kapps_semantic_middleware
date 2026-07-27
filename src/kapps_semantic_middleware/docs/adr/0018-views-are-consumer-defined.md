# A view belongs to its consumer, and is configured where the middleware is embedded

There is no single "the datamodel" for a resource. Each consumer defines its **own** ClassScope,
**rooted at the node that consumer cares about**, and states it in the code that embeds the
middleware library — not in the ontology. `SemanticMiddleware` gains a `class_scope` constructor
parameter carrying the **user view**: the northbound datamodel it materializes and REST-exposes.

```python
mw = SemanticMiddleware(
    mode="resource",
    resource_iri=tui.TransferUnit1,
    service_class=tu.TransferUnitService,
    class_scope=ClassScope.from_property_chains([
        [TU.hasConveyorBelt, TU.hasConveyorSpeed],
        [TU.hasConveyorBelt, TU.hasConveyorPosition],
        [TU.hasLightBarrier, TU.isOccupied],
    ]),
    ogm=ogm,
)
```

> **Corrected 2026-07-27 (#29, ADR 0019).** This example originally scoped a third level, reaching
> inside the parameter blanknode (`[TU.hasConveyorBelt, TU.hasConveyorSpeed, INF.hasValue]`).
> Reproduced live, that third element is **silently discarded**: a `ClassScope` terminates at a
> `COMPLEX` property and cannot select within it. A view names properties down to the parameter and
> no further. Excluding connection metadata is therefore done by a middleware-side projection — see
> **ADR 0019**, which amends the mechanism below while keeping its intent.

A connector for the same resource does not see the TransferUnit at all. Its scope is rooted at the
component it serves:

```python
ClassScope.from_property_chains([        # root: tui:ConveyorBelt1_left
    [TU.hasConveyorSpeed],
])
```

## Why

### N views, not a north/south pair

ADR 0015 called ClassScope the projection that separates southbound (how the middleware reaches the
PLC) from northbound (how peers reach the middleware). Working it through the controller shows the
pair is a special case of something more general: **every consumer projects what it needs, from
where it needs it**. The user view is rooted at the TransferUnit and stops at value/unit/access
mode; a connector's view is rooted at one belt and consists almost entirely of connection metadata.
Neither is "the" datamodel, and a connector re-scoping itself does not disturb what peers see.

This is also what keeps the IT-OT boundary real. Value, unit and MQTT topic hang off **one**
blanknode, so a scopeless fetch serves the broker address to every peer that GETs the resource — and
a controller could then bypass the middleware and drive the PLC over MQTT directly, which is the
coupling the architecture exists to remove. ~~The user view excludes connection metadata not by a
deny-list in router code but by simply not projecting it~~ — **superseded by ADR 0019**: a scope
cannot decline to project part of a blanknode, so the exclusion is a middleware-side projection
step. The "excluded by default rather than by a maintained list" property is preserved differently:
the projection hides what a registered connector declares about its own protocol (ADR 0020), so a
new protocol is covered when its connector is registered, not when someone remembers a deny-list.

### Configured in code, not authored in the ontology

ADR 0003 makes the ontology ground truth for *types*, and ADR 0015 made parameter wiring
ontology-first. A view is neither: it is a statement about **what this particular consumer is for**,
which the ontology cannot know. The domain code that weaves the library in is what knows.

This does not weaken the discovery story. KAPPS's flexibility claim is over **novel combinations of
known primitives** — a task made of grip/move/place may never have been seen in that combination,
but grip, move and place are known; a product may combine a screw and a gear that were each known.
Views are defined over known classes for exactly the same reason, and the system stays able to
handle combinations it has not seen.

### Access mode rides in the view

Settability is northbound (ADR 0015), so `inf:accessMode` is projected into the user view and
travels in the payload next to value and unit. The payload is therefore self-describing — a generic
UI renders an input where it finds `readwrite` and a read-only row where it finds `read` — and the
route generator gates the PUT verb off the same field (ADR 0017). A static facet repeating in a
live-value response costs nothing, because `OGM.commit` filters unchanged triples before committing.

### A standard path with an escape hatch, again

Discovery follows the same shape as ADR 0015's Path 1/Path 2 and ADR 0016's connector registry.
**Standard path:** name a resource class, get its individuals with the standard metadata rendered —
no SPARQL required, because the middleware and the OGM wrote that metadata and know what it means.
**Escape hatch:** supply SPARQL binding `?resource`, and every other bound variable becomes a
column. Setting up the common case must stay zero-SPARQL at twenty domain engineers to one ontology
engineer (ADR 0003); anything we have no standard for must still be expressible.

## Consequences

- Omitting `class_scope` falls back to today's scopeless `ogm.fetch(..., materialize=True)`, so
  scenarios 1 and 2 keep working unchanged and the parameter is additive. Measured (#29), that
  fallback materializes **the `id` and nothing else** — `ClassSpec.specify` returns early when the
  scope is empty, so the datamodel has no properties at all. This is **not** an error condition: the
  middleware acts on a projection, the knowledge graph holds the information, and a projection of a
  single individual is a legitimate one. Such a resource starts, registers and serves a datamodel
  with one field. Attributes may still be added afterwards by workflows. The failure surface is at
  *use*, not construction, and already exists: writing an absent attribute raises
  (`ValueError: object has no field ...`, pydantic `extra="forbid"`), and committing an undeclared
  property raises from `ClassSpec.specify` under scope hydration.
- A consumer that opens a resource **GETs its REST datamodel** and renders the returned tree, rather
  than fetching structure from the graph under a view of its own. The view is stated once, by the
  resource's own middleware; consumers cannot drift from it because it is what they are served. The
  controller therefore carries no ClassScope — it touches the graph only for discovery.
- Liveness is read from `svc:address` plus `svc:lastHeartbeat` freshness against a configurable
  threshold (default 90s, matching `staleness_threshold`), computed consumer-side. A process killed
  without deregistering goes stale on its own, with no watchdog instance required.
- Views defined in Python are invisible to the graph, so nothing validates that a view matches what
  an instance actually carries; a chain naming a property the instance lacks simply projects nothing.
- Amends ADR 0015: the southbound/northbound pair is generalized to per-consumer views, and the
  Open-World startup-wiring table is unchanged.

Resolves part of wayfinder ticket #32 under map #24.
