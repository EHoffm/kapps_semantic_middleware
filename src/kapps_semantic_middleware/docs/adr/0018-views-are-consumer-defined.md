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
> no further. Connection metadata is excluded not by the view and not by a middleware step, but by the
> `rdfs:range` restriction never declaring it — see the correction below (ADR 0019 superseded).

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

This is also what keeps the IT-OT boundary real: a peer that could read the broker address could
bypass the middleware and drive the PLC over MQTT directly, which is the coupling the architecture
exists to remove.

> **Corrected twice, settled 2026-07-27 (#25/#28).** This paragraph originally argued that value,
> unit and MQTT topic share one blanknode, so a scopeless fetch would serve the broker address to
> every peer — and that the *view* prevents it by not projecting it. Both halves were wrong.
>
> A scope cannot decline to project part of a blanknode (ADR 0019), so it was never the view's doing.
> But no middleware step is needed either: a parameter materializes to exactly what its property's
> `rdfs:range` restriction declares, and the domain ontology deliberately declares **only** domain
> content plus the access-mode marker. Connection metadata is in **no** restriction — the domain TBox
> and a connector's `inf:` TBox are unconnected, and the middleware joins them at runtime when the
> resource is instantiated. So the broker address is dropped before a datamodel exists.
>
> **The restriction is the projection**, and it is excluded by default in the strongest sense: a new
> protocol's metadata is invisible northbound because nobody ever declared it, not because anybody
> remembered a deny-list. ADR 0019 is superseded and its implementation issue closed unbuilt.

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
route generator gates the PUT verb off the same field (ADR 0017). ~~A static facet repeating in a
live-value response costs nothing, because `OGM.commit` filters unchanged triples before committing.~~

> **Corrected 2026-07-27 (#28).** `OGM.commit` does **not** filter unchanged triples for a complex
> property. `to_triples` mints a fresh `genid-{uuid4}` blank node on every serialization, and `diff`
> compares whole blank-node groups — so the groups never compare equal and **every commit deletes and
> recreates the entire parameter node**, even with no changes. Worse, the new node is built from the
> materialized instance, so any triple the ClassSpec does not declare — the connection metadata — is
> orphaned. Filed as SAWeindel/kapps_ogm#4. The conclusion above still holds once that lands; until
> then, do not commit a parameter node.

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
