# The northbound projection is middleware-side; a ClassScope cannot select within a parameter

A `ClassScope` selects **which** parameters a consumer sees. It cannot select **within** one. The
connection metadata that must not travel northbound is therefore removed by a **projection step in
the middleware**, applied to the materialized datamodel before it is REST-exposed — not by the view
itself declining to fetch it.

This amends ADR 0018, whose intent (a view belongs to its consumer; peers must not learn the broker
address) is preserved, and whose mechanism (the user view simply does not project connection
metadata) is not achievable.

## Why

### The mechanism ADR 0018 assumed does not exist

ADR 0018's worked example scopes three levels deep, reaching inside the parameter blanknode:

```python
[TU.hasConveyorBelt, TU.hasConveyorSpeed, INF.hasValue],
[TU.hasConveyorBelt, TU.hasConveyorSpeed, TU.hasUnit],
```

Reproduced live against `tui:TransferUnit1` (#29), that third element is **silently discarded**. Three
mechanics in `kapps_ogm` combine to make a blanknode's contents fixed and identical for every consumer:

1. `OGM._fetch_complex_property` issues a bare `?bnode ?property ?value` — every property of the
   blanknode, with no filter applied and no scope consulted (`kapps_ogm/ogm.py`).
2. `PropertySpec.specify` routes a `COMPLEX` property to `_specify_complex_property`, which takes no
   `nested_scope` argument at all. A chain element below a complex property is dropped without a
   warning, let alone an error.
3. The blanknode's shape comes from the property's `rdfs:range` **`owl:Restriction`** — the TBox —
   so it is a property of the ontology, not of the consumer. Instance triples the restriction does
   not declare are dropped at materialization (`NodeValidator`, non-strict, warning only); this was
   confirmed by `rdfs:comment` surviving the fetch and vanishing from the materialized model.

A view can therefore stop *at* `tu:hasConveyorSpeed`. It cannot stop *inside* it.

### The alternatives were worse or unavailable

**A second property over the same blanknode**, each with its own restriction — a northbound property
declaring value/unit and a southbound one declaring topic/broker — would have given two genuine views
for free. It is ruled out: `PropertySpec.specify` raises on any property resolving to more than one
`rdfs:range`, and the interface hierarchy is already superproperty-based, so ranges would collide by
inheritance. (Root ADR 0002 fixes the raise, but the shape stays one-range-per-property.)

**Splitting connection metadata onto its own node**, reachable by an object property and therefore
genuinely prunable by a scope, would have made ADR 0018 work verbatim. Rejected: the
metadata-on-a-blanknode pattern is locked across the circular factory — RDF has no properties about
properties — and the authoritative upstream TransferUnit ontology puts the topic on the parameter
blanknode. Diverging costs compatibility with the ontology we decided to reuse rather than paraphrase.

**Teaching `kapps_ogm` to prune inside a complex property** is new functionality in a sibling repo,
which root ADR 0001 forbids.

### The security property survives the move

What matters is that a peer cannot read the broker address from the served datamodel, not *where*
that exclusion is implemented. A middleware-side projection delivers it. It is weaker than ADR 0018's
"excluded by not being projected" in one respect — the metadata is materialized in-process before
being dropped, so a bug in the projection is a leak, where a bug in a scope was merely a missing
field. The compensating control is that the projection is driven by what a connector declares about
its own protocol (ADR 0020), not by a hand-maintained deny-list, so a new protocol's metadata is
covered the moment its connector is registered.

## Consequences

- ADR 0018's code example is wrong as written and is corrected there: a user view names properties
  down to the parameter, and no further.
- The projection needs to know which properties are connection metadata without the core knowing any
  protocol vocabulary. That is ADR 0020.
- Everything on a blanknode that is *not* connection metadata stays in the payload. A parameter is
  atomic northbound (value, unit, access mode read and written together), exactly as ADR 0017 has it.
- `rdfs:comment` and similar annotations on parameter blanknodes are dropped before they ever reach
  the projection, because the restriction does not declare them. Anything intended to reach a
  consumer must be declared in the restriction — which is now possible additively (root ADR 0002).
- Amends ADR 0018. Does not disturb ADR 0015's Open-World startup-wiring table.

Resolves part of wayfinder ticket #29 under map #24.
