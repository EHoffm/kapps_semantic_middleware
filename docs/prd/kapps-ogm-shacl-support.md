# PRD: SHACL support in kapps_ogm

**Origin**: `src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`
(`kapps_semantic_middleware`). Written during build of workflow
precondition/outcome representation. This needed SHACL. `kapps_ogm` has none.
**Status**: requirement capture only. No `kapps_ogm` code written from this document yet.
**Audience**: whoever picks up `kapps_ogm` v2.

## Problem

`kapps_ogm` has zero SHACL awareness today. Direct inspection confirmed this: no reference to
`shacl`, `ValidationReport`, or the `sh:` namespace exists anywhere in `kapps_ogm` or
`graph_db_interface`. Two independent needs in `kapps_semantic_middleware` want SHACL support.
Both currently cannot get it from `kapps_ogm`:

1. **Reading workflow signatures.** Workflow/StateProperty classes carry a `sh:NodeShape`
   (`sh:targetClass`). This describes their precondition/outcome properties (see the SHACL Interop
   ADR referenced above).
   `kapps_semantic_middleware` needs to turn that shape into a typed, validated Pydantic model.
   This should be the same kind of model that `ClassSpec.to_pydantic_model()` already produces
   for OWL-Restriction-based `COMPLEX` properties. SHACL shapes are not parsed at all today.
   This logic is currently hand-written inside `kapps_semantic_middleware` as a temporary
   duplicate of what `PropertySpec.specify()` already does for the OWL-Restriction case.

2. **Interpretation of SHACL validation rejections.** When GraphDB rejects a commit because a
   SHACL constraint is violated (e.g. UC2's `:FlexConveyorModuleShape` `sh:maxCount`
   example from the paper), the rejection currently surfaces through
   `graph_db_interface.GraphDbException` as an unparsed string: `f"Error while querying
   GraphDB ({status_code}) - {response.text}"`. The SHACL `ValidationReport` (focus
   node, constraint, message) is embedded as raw, unstructured Turtle/RDF text inside that
   string. `kapps_ogm.OGM.commit()` wraps DB failures in a bare `Exception(...)` on top of
   that. Nothing in either library extracts `sh:focusNode`/`sh:resultPath`/
   `sh:sourceConstraintComponent`/`sh:resultMessage` into a structured, catchable form.

## Requirements

- **R1 — Read SHACL shapes into ClassSpec.** Given a class IRI, resolve any `sh:NodeShape`
  targeting it (`sh:targetClass`). Turn it into the same `PropertySpec`-based representation
  `ClassSpec` already builds from OWL Restrictions. `to_pydantic_model()` produces an
  equivalent validated model regardless of which mechanism (OWL Restriction or SHACL)
  described the shape. At minimum: `sh:path`, `sh:datatype`/`sh:class` (→ `LITERAL`/`OBJECT`
  as today), `sh:minCount`/`sh:maxCount` (→ the existing `min_count`/`max_count` cardinality
  handling). `sh:node` (nested shapes, needed for the precondition/outcome indirection
  described in the SHACL Interop ADR referenced above) should map onto the existing
  nested-`ClassSpec`/`COMPLEX` handling.
- **R2 — Structured SHACL validation errors.** A dedicated exception type exists (in
  `graph_db_interface`, surfaced through `kapps_ogm`). It carries parsed `sh:focusNode`,
  `sh:resultPath`, `sh:sourceConstraintComponent`, `sh:resultMessage`,
  `sh:sourceShape`. Not a string to be re-parsed by every caller. GraphDB's SHACL
  validation reports are themselves RDF (see the paper's own Listing 2). This is a parsing
  problem GraphDB has already solved on its side. Just decode back into Python objects on
  ours.
- **R3 — No change to the OWL-Restriction path.** `COMPLEX` properties derived from
  `owl:Restriction` blank nodes must keep working exactly as they do today. SHACL support is
  additive, not a replacement.
- **R4 — Read-only is sufficient for the initiating use case.** `kapps_semantic_middleware`
  does not need `kapps_ogm` to *generate*/write SHACL shapes. Per
  `src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`,
  Workflow/Capability/Service classes and their shapes are pre-authored by ontology engineers.
  They are not
  minted at runtime. R1 is a read/parse requirement only. (A future generation capability may
  still be worth having for other consumers. It is out of scope for the requirement this PRD
  originates from.)

## Non-goals

- Replacement of GraphDB's own SHACL enforcement. That stays server-side. The architecture
  intends this. This is only about `kapps_ogm` understanding shapes that already exist and errors
  GraphDB already raised.
- A general-purpose SHACL engine in Python (no need to *evaluate* shapes client-side. GraphDB
  already does that on write).

## Suggested shape (non-binding)

Something like a `hydration_level`-agnostic extension to `ClassSpec.specify()` exists. After
resolution of `rdfs:domain`-based properties as today, additionally query for
`sh:NodeShape`/`sh:targetClass` that point at the class. Fold `sh:property` entries into
the same `properties: dict[IRI, PropertySpec]` structure. Callers cannot tell from `to_pydantic_model()`
onward whether a given field came from an OWL Restriction or a SHACL shape. Callers do not need to
know this.
