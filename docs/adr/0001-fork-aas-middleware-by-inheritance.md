# Fork aas_middleware by inheritance, reimplement locally over time

`SemanticMiddleware` subclasses `aas_middleware.Middleware` and reuses its `workflow()`
decorator, connector protocol, and REST/FastAPI/lifespan machinery directly, rather than
writing a fresh middleware from scratch. `aas_middleware`'s AAS-specific parts (data model,
persistence layer, `AasMiddleware` subclass) are not touched — only the orchestration,
connector, and REST core, which is already data-model-agnostic.

**Why**: the paper frames KAPPS's semantic middleware as a "refactor" of `aas_middleware`
with the AAS-specific parts removed, not a rewrite. The orchestration/connector/REST core
(`workflow()`, `Connector` protocol, lifespan hooks) is real, working, data-model-agnostic
code — writing it again from scratch before proving out the knowledge-graph-registration
layer on top of it would be pure cost with no corresponding benefit. `__init__.py`'s
migration comment ("as each layer is migrated locally, swap the import") already commits to
an incremental strategy: depend on `aas_middleware` now, replace pieces with local
implementations one at a time as they're understood well enough to own.

**Consequence**: `kapps_semantic_middleware` inherits `aas_middleware`'s naming/vocabulary
(`workflow`, `Connector`, `capability=` kwarg) even where it doesn't perfectly match the
paper's own terms, rather than introducing a second vocabulary on day one.
