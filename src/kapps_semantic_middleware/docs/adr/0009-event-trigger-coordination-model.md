# Inter-service coordination is an event trigger over a graph-backed operation queue

Services coordinate by **passing Operations through the graph and firing an event trigger**, not by
synchronous RPC. The caller **dispatches**: it creates the Operation individual in the graph
(via the OGM write path, addressed to a target Resource through its Capability) and then
**triggers the receiver's `execute()`** — a built-in Workflow every resource-mode middleware
exposes on its REST API. The trigger carries only the Operation IRI. The payload lives in the
graph. `execute()` **enqueues** the Operation, `ogm.fetch`es it, hands it to an optional
domain callback (else leaves it `queued`), and returns immediately — it does not block on the
work or return a business result. The receiving domain later **pulls** the next Operation,
runs it, and records the outcome. This replaces the previous synchronous `execute()`, which
resolved an endpoint and blocked on an `httpx` POST to the workflow (see the amendment to ADR
0005 and the annotation on ADR 0002).

**Queue durability.** The Operation and its status are written to the graph *before* the trigger,
so the graph is the source of truth and the per-resource queue is an in-memory cache. On
startup a middleware reconstructs its queue by querying the graph for its own `queued`
Operations **and reclaiming its own orphaned `running` ones**. A missed trigger (receiver briefly
down) or a restart therefore loses no work. The event trigger is a latency optimization over a
self-healing baseline, and a `watchdog`-mode instance centrally sweeps a *dead* resource's
stranded Operations rather than every resource polling (ADR 0007). Chosen over a continuous
per-resource poll because ~20 resources against one graph should not each poll, and over a
purely in-memory queue because that silently drops work on restart.

**Status lifecycle.** An Operation moves `queued → running → done | failed`. Execution
provenance (which Workflow ran it, when, the result) is written **as part of the terminal
transition**, so the status *is* the provenance record — the old separate `svc:executionSuccess`
boolean is dropped (`done` vs `failed` already carries it). See ADR 0010 for the pull-and-run
context manager that owns these transitions, and ADR 0012 for where the status vocabulary lives
(`svc:`, as middleware coordination).

**Recovery is never a silent physical replay.** An orphaned `running` Operation — its resource
crashed mid-execution, found at startup-pull or by the watchdog — transitions to `failed`
(carrying any dumped resource state), and the planner/domain decides whether to dispatch a
fresh Operation. Physical operations are frequently not safely repeatable (a half-driven screw,
a mid-transport), so recovery is explicit, never an automatic re-actuation.

**Consequence.** The event/push-notification primitive (R8 — the sender being notified when an
Operation reaches a status) is **not** required and stays deferred (per #4): the model is
poll/queue-based. The scenarios and use cases are learning vehicles for this model, not fixed
production contracts — if building them exposes friction in how the built-in (non-domain)
workflows are shaped, the coordination internals here are the thing to rethink, not the
scenario. Promotes the resolution of
[#4](https://github.com/EHoffm/kapps_semantic_middleware/issues/4).
