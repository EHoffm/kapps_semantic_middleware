# StateProperties are marks over the resource's aas datamodel, not getter-backed routes

A StateProperty is a **semantic mark over one field of the resource's aas_middleware
datamodel**, not a middleware-owned getter route. The datamodel — materialized at startup from
graph ground truth and kept live by connectors (ADR 0006; MQTT in scenario3, #28) — is the
single source of truth for every state *value*. `@mw.state` no longer mounts a `GET
/state/{name}` route backed by a Python getter; it **marks** an existing datamodel field for
promotion into the knowledge graph and reuses the framework's generated CRUD REST API
(`generate_rest_api_for_data_model`, already stood up in resource mode by
`_load_resource_datamodel`) as the field's read/write surface.

This supersedes the getter-backed StateProperty mechanism (the `/state/{name}` route) and
refines the endpoint half of ADR 0013: a StateProperty's `svc:endpoint` now points at the
field's datamodel CRUD route, which already serves `GET` (read) and `PUT` (write) at one URL.

## Why

**The setter surface already exists — reuse it.** #27 asked how a *remote* caller sets a
mutable StateProperty. Rather than invent a `PUT /state/{name}`, we reuse aas_middleware's CRUD
REST API, which already exposes `PUT /{Model}/{id}/{attribute}/` implemented as `provide() →
setattr → connector.consume` (`aas_middleware/middleware/rest_routers.py`). The
`connector.consume` step is precisely the seam an outbound MQTT connector (#28) hooks to
propagate a setpoint to the PLC. A parallel setter route would duplicate that machinery and
bypass the connector seam.

**One backing store, not two.** A getter-backed read surface plus a datamodel-backed write
surface would be two sources of truth for the same value, needing reconciliation. Unifying on
the datamodel — the value lives in one place, fed by the PLC over MQTT and read/written through
the framework CRUD — removes the split. The live value is still never *persisted to the graph*
(**scoped by ADR 0024**: that is the *locator* pattern, not a middleware invariant — a slowly-changing
parameter may legitimately be committed, and the middleware enforces neither choice);
only the `svc:endpoint` triple is written (ADR 0013 unchanged on that point).

**Direct REST, not Operation-routed.** Consistent with ADR 0013 (a setpoint is an idempotent
control variable, not a task) and with scenario2's direct discover-and-invoke pattern, a set is
a synchronous `PUT` to the discovered endpoint — no `cfc:Operation`, no event-trigger queue (ADR
0009). Remote discover-and-set mirrors scenario2's `_discover_door_endpoints`: SPARQL for the
`svc:SettableStateProperty` by `rdf:type`, read its `svc:endpoint`, `PUT` the value; response
and error shapes are the framework's (`{"message": ...}`, 400 on exception), reused.

**Exposure is by explicit mark, per ADR 0003.** The datamodel carries plumbing fields (ids,
counters, heartbeats) that are not semantic states. Only fields marked with `@mw.state` become
discoverable `svc:StateProperty` individuals in the graph. Auto-promoting every datamodel field
would re-introduce exactly the auto-derivation ADR 0003 rejected, and would flood the graph at
this project's twenty-domain-engineers-to-one-ontology-engineer scale. `@mw.state` is therefore
the curating *semantic lens* over the datamodel.

**The mark gates the verbs — structural read-only.** Settability is carried by the class (ADR
0013: `svc:SettableStateProperty` vs `svc:StateProperty`). The mark uses it to gate the
advertised REST surface: a settable field exposes `GET`+`PUT` (and gets an outbound MQTT
connector, #28); a read-only field exposes `GET` only, with no `PUT` and no outbound connector,
so a sensor is structurally unwritable through the advertised surface — not merely advised
against.

## Consequence

- **The getter-backed `/state/{name}` route is retired.** `@mw.state`'s implementation changes
  from "mount a getter route" to "mark a datamodel field": register the `svc:StateProperty` /
  `svc:SettableStateProperty` individual, set `svc:endpoint` to the field's CRUD route, and gate
  its verbs by class.
- **Existing getter-based states migrate to datamodel fields.** Scenario2's `door_status`
  (currently a Python getter) becomes a datamodel field. This is an implementation-level
  migration of a learning-vehicle scenario; ADR 0013's claim that the *ontology* change is
  non-breaking still holds — scenario2's ttl is unaffected, only its Python.
- **Refines ADR 0013's endpoint.** `svc:endpoint` = the datamodel CRUD route (one URL, GET+PUT),
  not `/state/{name}`. Discovery-by-`rdf:type` and "one endpoint, no new property" (ADR 0013)
  are unchanged; only the physical route moves.
- **Narrows #36.** The vocab additions (`svc:SettableStateProperty` in `service.ttl` +
  `vocabulary.py`) stand; #36's registration/decorator slice is subsumed by this refactor.
- **Depends on #28 and #29.** The datamodel must materialize the marked fields (#29) and wire
  the inbound/outbound MQTT connectors (#28) before the end-to-end settable path runs; the
  scenario3 integration ticket (#34) sequences the implementation set.
- SHACL validation of the write payload remains out of scope (ADR 0013).

Resolves wayfinder ticket #27 under map #24.

---

**Amendment (2026-07-23, ADR 0015).** Superseded in part. The mechanism here — the state value lives
in the aas datamodel, read/written through the framework CRUD, kept live by a connector — becomes
**Path 1** (the automatic, ontology-driven default) of ADR 0015. But `@mw.state` is no longer *how a
state is declared*: the parameter is authored in the domain ontology and the middleware wires it with
no decorator. `@mw.state` survives only as **Path 2**, the `@property`-style escape hatch for
parameters whose retrieval/actuation is more complex than a direct connector mapping. #37 is
superseded/absorbed by ADR 0015's handoff.
