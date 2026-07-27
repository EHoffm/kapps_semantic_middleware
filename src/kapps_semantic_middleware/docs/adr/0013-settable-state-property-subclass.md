# Settable state is `svc:SettableStateProperty`, a specialization of the readable `svc:StateProperty`

A StateProperty a consumer can *write* (set), not only read, is modelled as
`svc:SettableStateProperty`, a subclass of `svc:StateProperty`. Every StateProperty is
readable — that is the base class's meaning — and settability is a *specialization* that adds a
write access mode on top. There is **no** separate read-only class: a read-only state is simply
a `svc:StateProperty` (through its domain subclass, exactly as today).

Concretely, a TransferUnit's conveyor speed is one read-write control variable —
`tu:ConveyorSpeedProperty rdfs:subClassOf svc:SettableStateProperty` — read and set at the same
`svc:endpoint` (GET reads, PUT/POST sets; the REST shape is issue #27's, not this ADR's). A
light barrier is `rdfs:subClassOf svc:StateProperty` (readable only).

## Why

**Not a Workflow.** Setting a setpoint was considered as an ordinary `svc:Workflow` — a
`tu:SetConveyorSpeed` workflow realizing a "set" Capability, dispatched as an Operation through
the event-trigger queue (ADR 0009). Rejected: a conveyor-speed setpoint is an idempotent,
high-frequency control variable, not a discrete task with a `queued → running → done` lifecycle
and per-invocation provenance. Modelling it as a Workflow fragments one quantity ("conveyor
speed") into a read-StateProperty and a write-Workflow that a discoverer must find separately
and *know* are the same underlying value, and wraps every speed nudge in an Operation
individual. Keeping read and write as one individual, discovered as one property, matches how
the domain (and OPC-UA-style automation) treats a settable value.

**Readability is universal, so read-only is the base — not a sibling.** An earlier cut made
`svc:StateProperty` abstract with `svc:ReadOnlyStateProperty` and `svc:SettableStateProperty` as
symmetric siblings. Dropped for two reasons. First, "mutable/immutable" names the wrong axis: a
read-only sensor value (a light barrier, blocked → clear) mutates constantly; the real
distinction is whether a *consumer* can write it — settable-vs-not, not mutable-vs-not. Second,
and decisively, readability is *universal* — every StateProperty is readable — so it belongs on
the base class, and writability is a genuine specialization (`SettableStateProperty` **is-a**
readable StateProperty, plus a setter). A symmetric Settable/ReadOnly split would have forced
`svc:StateProperty` abstract and re-parented every existing read-only domain class (e.g.
scenario2's `ex:DoorStatusStateProperty`) for no semantic gain. Under the specialization model
those classes are already correct and untouched.

**Ground-truth in the type, no flag.** Consistent with ADR 0003, settability is carried by the
class, not by a decorator argument: `@mw.state` takes no `settable=` flag, the same way
`@mw.workflow` takes no `is_workflow=`. Registration infers settability by testing whether
`state_property_class` is a subclass of `svc:SettableStateProperty` — an extension of the
class-existence validation it already performs — and (once the setter mechanism of #27 exists)
cross-validates any supplied setter against that class at startup. Discovery of "what can I set"
is therefore a plain `rdf:type` query; **no** new capability, object property, or endpoint
property is introduced — the existing `svc:providesCapability` link and single `svc:endpoint`
are reused unchanged.

## Consequence

- The `svc:` vocabulary gains exactly one class, `svc:SettableStateProperty rdfs:subClassOf
  svc:StateProperty`, plus a clarified `svc:StateProperty` comment (readable base; settable is a
  specialization). No new properties. `svc:StateProperty` stays **concrete**, so existing
  read-only subclasses (scenario2) are unaffected — no migration.
- The write path itself — the PUT/POST endpoint shape, how the setter callable reaches
  `@mw.state`, the remote discover-and-set pattern, and error semantics — is designed separately
  (issue #27) and composes with the MQTT publish path (#28).
- A SHACL shape constraining the *write* payload (e.g. speed ∈ [0, maxSpeed]) is where ADR
  0003's per-class-shape pattern would eventually live — on `svc:SettableStateProperty`
  subclasses — but authoring and validating it is out of scope for this effort (deferred with
  the rest of SHACL Interop).
- Handoff: the `service.ttl` + `vocabulary.py` additions and the registration
  settability-detection are filed as a `ready-for-agent` implementation issue; no middleware
  code is written in this design effort. Resolves wayfinder ticket #26 under map #24.

---

**Amendment (2026-07-23, ADR 0015).** Superseded in part. The settable-vs-read-only *distinction*
still holds, but it is **no longer carried by a `svc:SettableStateProperty` subclass**. Under ADR
0015 a state is an interface-accessible parameter and settability is a **facet** on it (an access
mode, e.g. `inf:accessMode "read" | "readwrite"`) that a ClassScope projects. The
class-not-a-flag reasoning above stands as the rationale for keeping settability ground-truth in the
graph, but the concrete vocabulary (`svc:SettableStateProperty`, `svc:StateProperty`) is dropped —
`svc:StateProperty` retires into `inf:InterfaceAccessibleParameter`. #36 is superseded.
