# Brownfield gap analysis — Semantic Middleware core vs. the decided architecture

**Date:** 2026-07-17
**Scope:** the middleware itself — the runtime facade (`src/kapps_semantic_middleware/`) **and**
the ontology stack (`ontology/service.ttl` + the decided `cfc:`/`mes:`/`svc:` layering). The
use cases / examples are **out of scope** here (they are the downstream build tracked by
[Map #2](https://github.com/EHoffm/kapps_semantic_middleware/issues/2)).
**Purpose:** establish ground truth — *what the code does today* versus *what the resolved
wayfinder tickets say it should be* — to seed a brownfield `grill → PRD → issues` pass. This
is an **audit, not a set of decisions**; the keep/refactor/add/replace verdicts below are
*proposals* for the grilling to confirm, not settled calls.
**Sources:** direct read of `middleware.py`, `registration.py`, `ontology/service.ttl`,
`connectors/`, `shacl_interop/`, the Core Middleware ADRs (0001–0008), and the resolved
tickets [#4 coordination](https://github.com/EHoffm/kapps_semantic_middleware/issues/4),
[#5 SHACL](https://github.com/EHoffm/kapps_semantic_middleware/issues/5),
[#6 layout](https://github.com/EHoffm/kapps_semantic_middleware/issues/6),
[#7 handover](https://github.com/EHoffm/kapps_semantic_middleware/issues/7), plus the open
[#8](https://github.com/EHoffm/kapps_semantic_middleware/issues/8) /
[#9](https://github.com/EHoffm/kapps_semantic_middleware/issues/9) /
[#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10).

**Verdict legend:** **KEEP** (matches intent, no change) · **REFACTOR** (exists but semantics
must change) · **ADD** (absent, must be built) · **REPLACE** (present implementation is the
wrong model).

---

## Headline

The facade's **registration / execution-resolution / liveness** half exists and largely
matches intent. The entire **coordination + handover** half that Map #2 designed **does not
exist yet**, and the one piece that *looks* built — `execute()` — implements the **old
synchronous-RPC model**, not the decided doorbell/queue/pull model. So this is not "add the
missing methods to a sound base": it is **one load-bearing refactor (`execute()`) plus a
cluster of new machinery hanging off it, plus a new ontology layer.**

---

## 1. Runtime facade (code)

| Capability | In the code today | Decided target | Gap | Verdict |
|---|---|---|---|---|
| **Registration** `@workflow` / `@state` → Service/Workflow/Capability/StateProperty in the KG | Present & working (`middleware.py:239–369`, `registration.py`); honors ADR 0002/0003 (classes pre-exist, Operation→Capability→Workflow) | Unchanged | none | **KEEP** |
| **Execution resolution** Operation → Capability → Workflow → endpoint URL | Present (`resolve_operation_endpoint`, `middleware.py:398`) | Still needed as the *resolution* step | none in resolution itself | **KEEP** |
| **`execute()` semantics** | **Synchronous RPC**: resolve endpoint → `httpx` POST to the workflow URL → record provenance → return result (`middleware.py:371–418`) | **Doorbell** ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4)): receiver *enqueues* the operation, fetches its object from the graph (`ogm.fetch`), passes to an optional domain callback else sets status `queued`; the domain *pulls*. Not a blocking request/response. | Fundamental model mismatch — current `execute()` blocks on the workflow HTTP call; intended `execute()` returns after enqueue | **REFACTOR / REPLACE** |
| **Per-resource operation queue** | Absent (0 hits) | One queue per middleware instance ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4)) | entire component | **ADD** |
| **Domain `register_callback`** | Absent. (The 10 "callback" hits are `aas_middleware` `on_start_up`/`on_shutdown` lifecycle hooks — unrelated.) | Opt-in domain callback invoked on enqueue ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4)) | entire component | **ADD** |
| **`pop_next(class_scope)`** + domain-supplied `ClassScope` re-fetch | Absent | Domain pops next op → status `running` → re-`fetch` parameterized by a domain `ClassScope` ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4)) | entire component | **ADD** |
| **Operation status lifecycle** (`queued`/`running`/done/failed) | Absent (execution provenance is recorded per ADR, but there is no status state machine) | Explicit lifecycle on the operation ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4); exact vocab is fog) | entire component | **ADD** |
| **Failed-op resource state dump** to graph | Absent | On failure, dump the resource's `aas_middleware` datamodel to the graph ([#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4)) | entire component | **ADD** |
| **Handover primitive** `mw.handover(...)` context manager | Absent (0 hits) | Mode-aware CM: `__enter__` two checks (possession + `mes:hasHandoverAbility`) *outside* the txn, domain-owned body, `__exit__` one atomic possession switch ([#7](https://github.com/EHoffm/kapps_semantic_middleware/issues/7)) | entire component | **ADD** |
| **OGM-routed writes** (ADR 0008) | Present for registration/heartbeat/deregistration (all go through `register_service`/`update_heartbeat`/… on the OGM) | Unchanged as a policy | none for existing writes | **KEEP** |
| **Transactional-write discipline** (standing constraint: every write a transaction; precondition-checks *before* it; revert on failure) | Partially implicit — the atomic `DELETE/INSERT` exists in `graph_db_interface`, but the middleware doesn't yet systematically check-then-transact (there's no possession switch, no handover txn) | Systematic: checks outside, one clean revertible transaction inside | discipline not yet a code pattern | **ADD (enforce)** |
| **Heartbeat / watchdog** (`emit_heartbeat`, `sweep`, ADR 0007/0009) | Present & working (`middleware.py:158–237`) | Unchanged | none | **KEEP** |
| **`server` mode** | Stub — raises `NotImplementedError` (`middleware.py:131`) | Explicitly **out of scope** (Map #2) | none (intentional) | **KEEP** |
| **SHACL interop scaffold** `shape_from_typehints` | Present (`shacl_interop/`) | Temporary by its own ADR; destined for `kapps_ogm` v2 | none for this effort | **KEEP** |

## 2. Ontology stack

| Layer | In the repo today | Decided target | Gap | Verdict |
|---|---|---|---|---|
| **`cfc:` (Core)** — Operation/Capability/Resource/Task | External, published; referenced by `service.ttl` | Unchanged — the Core layer | none | **KEEP** |
| **`svc:` (Service)** — reachability only | `ontology/service.ttl`: Service/Workflow/StateProperty, `address`/`endpoint`/`lastHeartbeat`, resolution chain, execution provenance | Same, but **scope-guarded**: reachability / middleware-to-middleware only, **no domain/MES terms** ([#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10)) | must *not* absorb possession/handover | **KEEP (guard scope)** |
| **`mes:` (MES ontology)** — manufacturing-execution functionality | **Absent entirely** (no file, 0 references) | New module: `mes:hasPossession`/`mes:isPossessedBy`, `mes:hasHandoverAbility` + six enumerated individuals (`Put`/`Receive`/`Pick`/`Release`/`Pass`/`Retrieve`) ([#7](https://github.com/EHoffm/kapps_semantic_middleware/issues/7), [#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10)) | entire module + its namespace | **ADD** (blocked on [#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10) namespace decision) |

## 3. Architecture decided but not yet in the repo's own ADRs

The coordination model, handover primitive, transactional-write constraint, and ontology
layering are decided **only in the wayfinder tickets** — the Core Middleware ADR set still
stops at **0008** and contains none of them. A stateful `grill-with-docs` pass should
**promote the confirmed decisions into ADRs** (0009+ / a new MES-layering ADR) so `CONTEXT.md`
and the ADRs, not just the issue tracker, are the ground truth the builders read.

## 4. What breaks — test impact

Four project test files exist: `test_shape_from_typehints.py`, `test_liveness_integration.py`,
`test_scenario1_integration.py`, `test_scenario2_integration.py`. The **scenario integration
tests exercise `execute()`** in its current synchronous-RPC form, so the `execute()` refactor
will break them — they encode the *old* model and must be rewritten alongside it. Liveness and
shape-from-typehints tests are orthogonal and should survive.

## 5. Suggested build sequence (a *seed* for grilling, not a decision)

Dependency order the grilling should pressure-test, not adopt uncritically:

1. **Ontology layering** ([#10](https://github.com/EHoffm/kapps_semantic_middleware/issues/10)) → mint the `mes:` module + possession/ability vocabulary. Everything domain-facing depends on the namespace.
2. **Coordination machinery** — the `execute()` refactor + operation queue + status lifecycle + domain callback + `pop_next(class_scope)` + failed-op state dump. This is the load-bearing cluster; the rest hangs off it.
3. **Handover primitive** ([#7](https://github.com/EHoffm/kapps_semantic_middleware/issues/7)) — depends on the `mes:` vocabulary (1) and the transactional-write discipline; its body relies on the doorbell from (2).
4. **Then** the UCs become buildable on a facade that matches its own spec (back to Map #2).

## 6. Open brownfield questions to resolve in the grilling

These are the decisions greenfield never had to make — the ones the grill pass exists to settle:

- **`execute()` transport.** ADR 0005 says `execute()` is a Python method, not REST — but the doorbell is cross-middleware. When middleware A rings middleware B's `execute()`, is that an in-process call, an HTTP call to B, or does the *current* workflow-endpoint HTTP POST survive as the transport *inside* the new model? Reconcile the decided doorbell with the existing HTTP invoke.
- **Keep vs. rewrite `execute()`'s provenance recording** (`record_operation_outcome`) — does it fold into the new status lifecycle, or stay a separate concern?
- **Queue scope & lifetime** — in-memory per instance, or graph-backed? What happens to `queued` ops across a restart?
- **How much of the current scenario tests is salvageable** vs. rewritten against the new model.
- **Migration safety** — is the facade rebuilt in place on a branch, or is there a parallel path so the working registration/liveness half keeps passing while `execute()` is reworked?
- **ADR promotion** — which decided tickets become ADRs, and do any existing ADRs (esp. 0002/0005) need amending to reflect the doorbell model?

---

*This document is ground truth for a brownfield `grill → PRD → issues` pass. Open the grilling
in a fresh session and reference this file; do not re-derive the decisions already recorded in
the tickets above — resolve only the open questions in §6.*
