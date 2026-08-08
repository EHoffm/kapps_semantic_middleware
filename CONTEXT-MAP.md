# Context Map

## Contexts

- [Core Middleware](./src/kapps_semantic_middleware/CONTEXT.md) — the middleware library itself.
  It holds the Service/Workflow/Capability/Operation/Mode registration machinery and the
  execution machinery.
- [SHACL Interop](./src/kapps_semantic_middleware/shacl_interop/CONTEXT.md) — the temporary SHACL
  seam for workflow precondition shapes and outcome shapes. It generates and parses them. It is
  explicit scaffolding, will move to `kapps_ogm` (see its ADR 0001).
- [Example Scenarios](./examples/CONTEXT.md) — self-contained demonstration notebooks, plus the
  seed-data logic and the ontology-provisioning logic under them. That logic makes each notebook
  reproducible against a dummy repository, and never against the production state.
- [TransferUnit Factory](./demo/transferunits/CONTEXT.md) — the runnable multi-process demo. A
  launcher seeds N units and starts one process per participant (ADR 0029). Its decisions live
  with the Core Middleware ADRs, next to ADR 0029.
- [Module Requirements](./docs/prd/) — requirements this project places on sibling KAPPS-family
  modules (`kapps_ogm`, the not-yet-created visual-toolbox GUI). Not a code context: a collection
  of PRD documents, not a glossary + ADRs.

## Relationships

- **Core Middleware → SHACL Interop**: Core Middleware calls into SHACL Interop to read or write
  a shape. The shape belongs to a Workflow class or a StateProperty class. The call happens when
  `@mw.workflow` or `@mw.state` registers or resolves one. SHACL Interop has no dependency back
  on Core Middleware. It operates on class IRIs and shapes, and not on types of the Core Middleware.
- **Example Scenarios → Core Middleware**: Example Scenarios instantiate and exercise Core
  Middleware end-to-end, against the ontology and the instance data they seed themselves. Core Middleware
  has no dependency on Example Scenarios.
- **TransferUnit Factory → Core Middleware**: the factory runs several instances of the library
  in separate processes. That is one instance per unit, plus a controller. A monitor is
  milestone 2 (ADR 0032) and is not built. Core Middleware has no dependency on the factory.
- **Module Requirements** records obligations that Core Middleware and SHACL Interop place on
  `kapps_ogm` and the visual-toolbox repo. It does not depend on the code contexts, and no code
  context depends on it. It is a record for work that belongs elsewhere.

## Ontology-module layering

The vocabulary of the project is layered across three modules (Core Middleware ADR 0012):

- **`cfc:` — Core** (`.../Core#`): published, external, superior — `Operation`/`Capability`/
  `Resource`/`Task`. The system imports and specializes it. The system does not modify it.
- **`mes:` — MES** (`.../MES#`, `src/kapps_semantic_middleware/ontology/mes.ttl`): a
  **domain** ontology that imports Core and details it out — possession + handover ability.
  What domain experts touch.
- **`svc:` — Service** (`.../Service#`, `ontology/service.ttl`): middleware-to-middleware
  **reachability and coordination only**, domain code does not touch it. It holds Service, Workflow and
  StateProperty, the address, the endpoint and the heartbeat. It also holds the resolution chain,
  and an Operation's status and provenance.

`mes:` and `svc:` are siblings that both import Core. `mes:` is domain-facing, `svc:` is
middleware-facing.

## Where the ADRs live, and which context each one governs

Two directories hold architecture decision records. The directory names the owner of the decision.
The lists below name the context that each record governs.

- **`docs/adr/`** at the repo root — decisions above every context. How this repo relates to its
  sibling dependency repos, and how the contexts relate to each other.
- **`src/kapps_semantic_middleware/docs/adr/`** — decisions inside a context. One numbered sequence
  serves both the Core Middleware context and the TransferUnit Factory context.

Cite a root record as **root ADR 000n**. Cite the other sequence as **ADR 00nn**. Both sequences
start at 0001, so the prefix is not optional.

### Root records — above every context

| record | governs |
|---|---|
| root ADR 0001 | dependency wiring, and the bugfix policy for sibling repos |
| root ADR 0002 | a conjunctive `rdfs:range` is a `kapps_ogm` defect |
| root ADR 0003 | anonymous node identity is specified, not patched |
| root ADR 0004 | scenario parts live in the demo, and the core grows only generic features |

### Core Middleware records

ADR 0001 to ADR 0028, ADR 0031, **ADR 0033**, **ADR 0034** and **ADR 0035**. Some numbers in that
span retired into their successors: ADR 0013 and ADR 0014 retired into ADR 0015; ADR 0016 retired
into ADR 0023; ADR 0019 retired into ADR 0028. A number missing from that list is missing, not
retired. These records govern the library. They hold for every consumer of the middleware, and not
only for the demonstration.

ADR 0033 is a core record even though the demonstration forced it. It puts a REST binding descriptor
beside the MQTT one, so the connector seam reaches a peer middleware as readily as a device, and it
names no domain term.

ADR 0034 is core for the same reason and with a caveat of its own. The demonstration forced it, it
adds a public constructor argument rather than a domain term, and it deliberately keeps every
transport implementation out of `src/`. Its shape is provisional until the demo has used it: the
record says so, and says to revisit it once the factory runs.

ADR 0035 is core and sits lower than either. It says a write into persistence names the region of the
model that moved, so a connector is asked to write to its device only when its own parameter was
written. The mechanism lives in `aas_middleware_inf` under root ADR 0001's bugfix allowance, because
that is where the fan-out is; the record lives here because the invariant is this middleware's, and
because every future connector depends on it.

### TransferUnit Factory records

**ADR 0029, ADR 0030 and ADR 0032.** These govern the demonstration only. They stay in the same
numbered sequence, because they cite the core records constantly.

A factory record may correct a core record. ADR 0032 does exactly that. It retires the word "flavour"
from ADR 0020 and from the Core Middleware glossary. Read the core record first, and then read the
factory record that amends it.

**The correction runs both ways.** ADR 0033 is a core record that amends a factory one: it retires
ADR 0032's `Role` axis, because the axis rested on consumers having no connector wiring and they now
have it. Where a core and a factory record disagree, the later record wins whichever context it sits
in, and it says so explicitly in an amendment section rather than leaving the reader to date them.

### Example Scenarios records

None. The scenario walkthroughs under `examples/` hold no decisions of their own.
