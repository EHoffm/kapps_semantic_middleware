# Context Map

## Contexts

- [Core Middleware](./src/kapps_semantic_middleware/CONTEXT.md) — the Service/Workflow/
  Capability/Operation/Mode registration and execution machinery; the middleware library
  itself.
- [SHACL Interop](./src/kapps_semantic_middleware/shacl_interop/CONTEXT.md) — the temporary
  SHACL generation/parsing seam for workflow precondition/outcome shapes, explicitly
  scaffolding destined to move into `kapps_ogm` (see its ADR 0001).
- [Example Scenarios](./examples/CONTEXT.md) — self-contained demonstration notebooks and the
  seed-data/ontology-provisioning logic that makes them reproducible against a dummy
  repository rather than production state.
- [Module Requirements](./docs/prd/) — requirements this project places on sibling KAPPS-
  family modules (`kapps_ogm`, the not-yet-created visual-toolbox GUI). Not a code context:
  a collection of PRD documents, not a glossary + ADRs.

## Relationships

- **Core Middleware → SHACL Interop**: Core Middleware calls into SHACL Interop to read/write
  a Workflow or StateProperty class's precondition/outcome shape when `@mw.workflow`/
  `@mw.state` register or resolve one. SHACL Interop has no dependency back on Core
  Middleware — it operates on class IRIs and shapes, not on Core Middleware's own types.
- **Example Scenarios → Core Middleware**: Example Scenarios instantiate and exercise Core
  Middleware end-to-end, against ontology/instance data they seed themselves. Core Middleware
  has no dependency on Example Scenarios.
- **Module Requirements** records obligations that Core Middleware and SHACL Interop place on
  `kapps_ogm` and the visual-toolbox repo. It doesn't depend on, or get depended on by, the
  code contexts — it's a paper trail for work that belongs elsewhere.

## System-wide decisions

Decisions that don't belong to any single context (e.g. how this whole repo relates to its
sibling dependency repos) live in `docs/adr/` at the repo root, not inside any context.
