# A persistence write names the field that moved, and only that field's write leg is told

A write into persistence carries a second piece of information beside the value: **which region of
the model actually changed**. `PersistedConnector.consume` and `_notify_synced_connectors` take it
as `changed: ConnectionInfo`, and the fan-out notifies only the connectors that region covers.

The invariant this buys, stated positively:

> **A connector is asked to write to its device only when its own parameter was written.**

`None` means "the whole model changed" and notifies everything, which is the historical behaviour
and stays the default. Matching is by **prefix**, not equality: an unspecified level in a
`ConnectionInfo` means *every* value at that level.

## Why

### The persistence layer is two levels coarser than everything else we do

Our unit of registration is the **parameter** — a belt's speed. `ConnectionInfo` expresses it with
four levels, and `middleware._wire_semantic_connectors` fills in all four. ADR 0017's routes address
the same atom. ADR 0028's projection works on the same atom. ADR 0023's binding descriptor recognizes
the same atom. Every part of this middleware agrees on what the addressable thing is.

`aas_middleware` does not. `add_synced_connector` resolves a connector's persistence connector with
`get_connector_by_data_model_and_model_id` — **two** of the four levels. `contained_model_id` and
`field_id` are dropped. So one TransferUnit's six connectors all hang off a single persistence
connector, and `_notify_synced_connectors` had no way to distinguish them:

```
                    ONE persistence connector = the whole TransferUnit
                                   │
        ┌──────────┬───────────┬───┴───┬───────────┬──────────┐
     left/read  left/WRITE  right/read right/WRITE front/read back/read
```

That is not a defect in the original design. `aas_middleware` was built around connectors registered
at the level of a whole datamodel, where "something changed, tell everyone" is exactly right. We are
the first consumer with **several independently writable fields on one model**, so we are the first
to need the finer statement.

### For a settable parameter, an unnecessary notification is a fabricated command

A write leg asked to re-derive its slice *publishes to its device*. Under ADR 0024's locator pattern
the parameter has one value slot, shared by the commanded and the observed value. So a write leg
re-deriving at the wrong moment publishes the last value the **device reported** onto the topic the
device treats as a **setpoint**.

The device then reads its own actual state back as a fresh command. #94 measured the result: a belt
sent to 3.0 m/s froze at 2.95 — exactly one ramp step short — with its *setpoint* holding a value
nobody commanded.

This is why the fix is not "skip a wasteful call". A notification to a connector whose field did not
move is not wasted work. It is an instruction to a machine.

### `origin` could not reach it, and widening `origin` would not either

ADR 0022's sibling record and the `origin` argument (kapps_semantic_middleware#92) already skip a
field's *own* write leg when that field's *own* read caused the notification. #94 arrives by two
routes that provably sit outside that:

- **A sibling's device read.** A light barrier's republish fans out onto a belt's write leg. The
  origin is the *barrier's* `ConnectionInfo`. The skip correctly does not fire.
- **An external write to a sibling field.** A PUT carries `origin=None` by design — there is no
  originating connector to exclude — and reaches every write leg on the resource.

Widening the skip to "any origin at all" fixes the first and leaves the second, which is the one
#82's algorithm hits in ordinary operation: write one belt while another is mid-ramp.

The right question is not *who supplied this value* but *what moved*. Those are different claims,
so they are different arguments.

### Prefix matching, because a write has four granularities

`update_persistence_with_value` has four branches — whole model, contained model, top-level field,
contained field — and only the last produces a fully specified `ConnectionInfo`. Under equality
matching a whole-model write would match no connector at all and notify **nothing**, silently
disabling the fan-out for the callers that most depend on it. `_covers` reads an unspecified level as
"every value at this level", so each branch scopes to exactly what it wrote and the whole-model
branch still reaches everything.

## Consequences

- **`mqtt_binding.serialize`'s "no observed value yet" guard changes character.** It used to fire in
  ordinary operation, because a parameter nothing had ever set was routinely asked to publish. It is
  now a genuine guard. It stays, because "asked to publish something never observed" is still a real
  error worth naming rather than encoding as JSON `null`.
- **A lap became measurable.** The freeze made "time until the peer reports the commanded value"
  uncompletable. Measured 2026-08-07 (`tests/test_lap_measurement.py`): transport is ~20 ms and the
  lap is otherwise ramp distance over ramp rate — 3.05 s for a 3.0 m/s move. `DEFAULT_TICK_SECONDS`
  stays 8.0, now measured rather than reasoned, clearing the slowest measured lap by 2.6x.
- **Every caller that writes one field should say so.** `rest_router._make_put_handler` does. A future
  route, workflow or connector that mutates a slice and calls `consume` with the whole model and no
  `changed` silently restores the defect for that path. The failure is quiet — an unbidden device
  write, not an exception.
- **`contained_model_id` is never `None` for our parameters**, even when the parameter sits on the
  root: `_wire_semantic_connectors` registers every binding with
  `contained_model_id=str(binding.resource_iri)`. A caller that leaves it `None` widens the scope to
  the whole resource. `_make_put_handler` passes `owner_id` unconditionally for this reason.
- **Bridging one parameter across two protocols still does not work**, and this ADR does not fix it.
  #92's skip compares `ConnectionInfo`, and a parameter's read and write legs deliberately share one
  — that is what makes it work — so it also skips any *other* connector on that field. Inbound MQTT
  with outbound OPC UA on one parameter would go nowhere. Nothing in this repo needs it; it is
  recorded here so the next person meets it as a known limit rather than a mystery.
- **Two BIDIRECTIONAL middleware instances over one resource remain a misconfiguration.** ADR 0022's
  second instance is a `TO_PERSISTENCE` monitor, which never writes. The test suite had to isolate
  `ConnectorSyncManager` between tests to stop two test files colliding on this; that singleton's
  missing deregistration path is a separate defect, filed separately.

Implements wayfinder ticket #94 under map #57. The mechanism lives in `aas_middleware_inf` under root
ADR 0001's bugfix allowance, with a CHANGELOG entry there.
