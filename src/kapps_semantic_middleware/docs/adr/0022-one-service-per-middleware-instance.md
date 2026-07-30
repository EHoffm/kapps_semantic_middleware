# A resource has one Service per middleware instance, not one Service

`mint_service_iri` discriminates by **instance**, so every middleware bound to a resource owns its
own `svc:Service` node, its own `svc:address`, and its own `svc:lastHeartbeat`. All of them link to
the resource by `svc:isServiceOf`, which the ontology has always modelled as many-to-one.

```turtle
tui:TransferUnit1_service_<discriminator>   a svc:Service ;
    svc:isServiceOf   tui:TransferUnit1 ;
    svc:address       "http://10.0.0.4:8000" ;
    svc:lastHeartbeat "2026-07-27T14:02:11Z" .

tui:TransferUnit1_service_<discriminator2>  a svc:Service ;     # the monitor
    svc:isServiceOf   tui:TransferUnit1 ;
    svc:address       "http://10.0.0.9:8001" .
```

The discriminator must be **stable across restarts of the same deployment** (so a restart re-uses its
node instead of orphaning one) and **distinct between concurrent instances**. Deriving it from the
instance's address satisfies both; the exact scheme is an implementation choice.

## Why

### One node cannot hold two instances

`mint_service_iri` returns `{resource_iri}_service` — purely a function of the resource — and
`register_service` **`_set`s** `svc:address`. Two middleware instances on one resource therefore
share a single node, with three consequences, none of them detectable at runtime:

- The second registration **overwrites** the first's address. Peers discover the resource and
  dispatch Operations to whichever instance started last — quite possibly the read-only monitor.
- Both heartbeat the same `svc:lastHeartbeat`, so the resource reports alive while either process
  lives. Liveness (ADR 0007) stops meaning what ADR 0018's discovery assumes it means.
- `_deregister_service` on either shutdown removes the shared node, so stopping the monitor makes the
  running controller undiscoverable.

The connector flags (ADR 0020) address none of this: they govern the device side, while this is the
graph side of the same two-instance scenario.

### Flavours out of the same puzzle pieces

Resource mode is a **library woven into a domain expert's Python package**, not a monolithic server.
Controller, monitor and inspector are configurations of one library, and a design that permits only
one instance per resource forces the alternative shape — a single privileged process that everything
else must go through. Making service identity per-instance is what lets the flavours coexist without
special-casing any of them.

### Discoverability without dispatchability

Registering the monitor rather than hiding it (a `register_service=False` flag was the alternative)
keeps its liveness honest and its REST surface findable, which is the point of a monitor. It does not
make it a target for work, because **ADR 0002 resolves an Operation via Capability**: a monitor
registers no workflows, therefore has no `cfc:Capability`, therefore is never selected — with no new
mechanism. Discoverable and un-dispatchable falls out of machinery that already exists.

## Consequences

- `mint_service_iri` gains an instance discriminator; it is no longer a pure function of the
  resource. Anything reconstructing a service IRI from a resource IRI alone must instead query
  `svc:isServiceOf`.
- Discovery may return **several** services for one resource. Consumers choose by address, liveness,
  or the capabilities each advertises — and must no longer assume exactly one.
- Deregistration and heartbeat become per-instance and therefore correct; a crashed instance goes
  stale on its own without affecting its siblings (ADR 0007 unchanged).
- Scenarios 1 and 2 are unaffected in behaviour: one instance per resource still yields one service,
  only its IRI changes. Any test asserting the literal `{resource_iri}_service` string must be
  updated.
- Amends the registration model behind ADR 0004; ADR 0002's Capability-based resolution and ADR
  0007's liveness model are relied upon, not changed.

Raised while grilling `autoregister_connectors` after wayfinder ticket #29, under map #24.
