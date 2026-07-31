# Three middleware modes: resource, server, watchdog

`SemanticMiddleware` takes a `mode` constructor parameter with three values:

- `"resource"` (built first): wraps one `resource_iri`. User-registered `@workflow`/`@state`
  functions are the REST-facing surface. Built-in functionality (`execute`, CRUD via the
  OGM) is exposed only as plain Python methods, not REST routes.
- `"server"` (not yet implemented): wraps no resource. `execute`/CRUD *are* the REST
  surface — e.g. a future "product server" whose entire purpose is to answer
  `fetch`/`ClassScope` requests against the graph for other services.
- `"watchdog"` (built alongside resource mode): wraps no resource, exposes little to no REST
  surface, and instead runs a sweep loop that deregisters (removes `address`/`endpoint` from)
  Service individuals whose heartbeat has gone stale.

**Why**: these three shapes were each raised independently during design (a bare
hello-world function; a future data-serving service with no physical resource; a
liveness-sweeping process with no resource *and* no meaningful REST surface) and turned out
not to be variations on one shape but three genuinely different answers to "what is this
middleware instance for." Rather than let that surface as three unrelated classes or three
sets of ad hoc constructor flags, `mode` makes the distinction explicit and exhaustive at
construction time. `execute`/CRUD existing as Python-only methods in resource mode but as the
REST surface in server mode follows directly from what each mode's purpose actually is: in
resource mode, workflows are the point and `execute` is plumbing a resource-mode instance
uses internally (e.g. to trigger *other* resources' capabilities). In server mode, there are
no workflows, so `execute`/CRUD have nothing to hide behind.

**Consequence**: `server` and `watchdog`-as-a-concept both existed as scope only at design
time. `watchdog`'s sweep logic was pulled into this session's build scope alongside resource
mode (see `src/kapps_semantic_middleware/docs/adr/0007-heartbeat-and-watchdog-mode.md`) once
its two-part decomposition (heartbeat + sweeper) became clear.
`server` mode remains a documented, reserved mode value with no implementation yet.

---

**Amendment (2026-07-17, event trigger model).** This ADR said `execute` is exposed *only* as a
plain Python method in resource mode. That is no longer true for `execute()` itself: under the
event trigger model (ADR 0009) `execute()` is the receiver-side intake, exposed as a **built-in
Workflow on the REST API** so a caller on another host can trigger it. The corrected resource-mode
REST surface is therefore: user-registered Workflows/StateProperties **plus the built-in
`execute()` event trigger**. Everything else stays Python-only — CRUD, and the transactional
context-manager surface (dispatch/`request`, pull-and-run, handover; ADR 0010) — none of which
is REST-exposed in resource mode.

**Amendment (2026-07-17, #13 — resource datamodel REST interface).** Resource mode now *also*
stands up a **CRUD REST API generated from the resource's own datamodel**: on startup the
middleware OGM-fetches the resource individual, materializes its `aas_middleware` datamodel, and
calls `generate_rest_api_for_data_model` (the `generate_rest_interface` path). This **relaxes the
"CRUD stays Python-only" stance** of the previous amendment: the *resource's own datamodel* is
REST-exposed so peers can read/observe it. What remains Python-only is the transactional
context-manager surface (`request`/dispatch, pull-and-run, handover; ADR 0010) and the graph-write
helpers — never REST-exposed in resource mode. The generation is best-effort (a resource with no
materializable data is skipped, not fatal), and the generated route path is currently derived
verbatim from the resource IRI (unwieldy — a cosmetic follow-up for #14).

---

**Amendment (2026-07-27, #32 — a controller is a resource-mode planner; `server` stays reserved).**
Scenario3's controller (it discovers TransferUnits through the graph and drives them over REST) was
the first real candidate for `server` mode, and it does not fit. This ADR defines `server` as a
*graph-serving* shape — "`execute`/CRUD *are* the REST surface … answering `fetch`/`ClassScope`
requests **for other services**". A controller is the mirror image: it *consumes* the graph and calls
*other* resources' endpoints, and nothing calls it inbound (nor in the v1.1 bootstrap, #35, which is
outbound too). Adopting `server` mode here would have meant redefining it, not implementing it. So
the controller is a **resource-mode planner** — its own `cfc:Resource` and `svc:Service` class,
exactly like scenario1's planner and scenario2's mobile robot — and `server` mode remains reserved
and unimplemented, recorded as Out of scope on map #24.

The scenario is a learning vehicle, and it surfaced a real defect in how that pattern was used:
scenario1's planner and scenario2's robot are *constructed* in resource mode but **never served**, so
`on_start_up` never fires, they never register, and they exist only to hold an `ogm`. "Resource mode"
was a label with no runtime consequence. The controller is served for real — it registers,
heartbeats, and appears in its own discovery list as a resource with no controllable parameters — and
scenarios 1 and 2 are retrofitted to match, so all three examples show one consistent pattern.

Resource mode is also the shape the library is *shipped* in: it is woven into domain code as a Python
library rather than run as a standalone server, which is why the view it exposes is a constructor
parameter (ADR 0018) — the embedding code is what knows what the instance is for.
