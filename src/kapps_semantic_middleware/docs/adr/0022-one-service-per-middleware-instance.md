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
instance's address satisfies both. The exact scheme is an implementation choice.

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

### Roles and wirings out of the same puzzle pieces

Resource mode is a **library woven into a domain expert's Python package**, not a monolithic server.
The three connector wirings are configurations of one library. A design that permits only one instance
per resource forces the alternative shape. That shape is a single privileged process, and everything
else must use it. Per-instance service identity is what lets the configurations coexist.

### Discoverability without dispatchability

Registering the monitor rather than hiding it (a `register_service=False` flag was the alternative)
keeps its liveness honest and its REST surface findable, which is the point of a monitor. It does not
make it a target for work, because **ADR 0002 resolves an Operation via Capability**: a monitor
registers no workflows, therefore has no `cfc:Capability`, therefore is never selected — with no new
mechanism. Discoverable and un-dispatchable falls out of machinery that already exists.

## Consequences

- `mint_service_iri` gains an instance discriminator. It is no longer a pure function of the
  resource. Anything reconstructing a service IRI from a resource IRI alone must instead query
  `svc:isServiceOf`.
- Discovery may return **several** services for one resource. Consumers choose by address, liveness,
  or the capabilities each advertises — and must no longer assume exactly one.
- Deregistration and heartbeat become per-instance and therefore correct. A crashed instance goes
  stale on its own without affecting its siblings (ADR 0007 unchanged).
- Scenarios 1 and 2 are unaffected in behavior: one instance per resource still yields one service,
  only its IRI changes. Any test asserting the literal `{resource_iri}_service` string must be
  updated.
- Amends the registration model behind ADR 0004; ADR 0002's Capability-based resolution and ADR
  0007's liveness model are relied upon, not changed.
- **ADR 0032 removes this decision's motivating example from scenario 3.** The controller and the
  monitor are consumers, and each roots at its own station resource. No two instances share a resource
  in the demo. This decision stays valid for a redundant pair, or for a restart before deregistration.
  Ticket #47 is therefore not a prerequisite of the monitor.

## The scheme, as implemented

The discriminator is the instance's **normalized address**, mangled with **`IRI.lined`**.
`normalize_address` lowercases scheme and netloc and strips a trailing slash; `IRI.lined` applies
the repo's total, invertible mangling (`_`→`__`, `:`→`_c_`, `/`→`_s_`, `.`→`_d_`, `#`→`_h_`).

```python
def mint_service_iri(resource_iri: IRI, address: str) -> IRI:
    return IRI(f"{resource_iri}_service_{IRI(normalize_address(address)).lined}")
```

So the hello resource served at `http://127.0.0.1:8993` registers as:

```
https://example.org/kapps-demo#hello_resource_service_http_c__s__s_127_d_0_d_0_d_1_c_8993
```

**`lined` rather than a hash**: ADR 0021 keeps production IRIs back-resolvable, and `IRI.from_lined`
reads the instance's address straight back off its node IRI. A hash would satisfy stability and
distinctness just as well, and would be shorter — it would also make the node opaque.

**Normalization earns its place** because `http://Host:8000/` and `http://host:8000` are one
deployment; minting two nodes for them would resurrect the orphaning this decision exists to
prevent. `address` is **required** for the same reason: a default would silently reinstate the
shared node. An address that is not absolute raises `ValueError` — no discriminator can be derived
from it.

Reconstructing a Service IRI from a resource IRI is replaced by `services_of_resource(ogm,
resource_iri, *, reachable_only=False)`, a read over `svc:isServiceOf`. `reachable_only` keeps the
Services that currently carry an `svc:address`, which is the set a consumer wants.

**The watchdog sweep still needs the same correction, and did not get it here.** It deregisters a
stale Service *and* fails its resource's stranded Operations. With one Service per resource those
were one statement; with two they are not, and a stale monitor now drags its live sibling's work
down with it. The obvious repair — fail them only when no sibling survives — is wrong in the other
direction, because a surviving monitor realizes no Workflow and would shield a dead controller's
queue forever. The correct predicate is per-Operation ("does any surviving Service realize this
Operation's Capability", ADR 0002), and `_reconstruct_queue` needs the same treatment. Left alone
deliberately rather than half-fixed; tracked as #63.

**Known limitation**: a deployment that changes its address orphans its old node. That is inherent
in deriving identity from the address, and this decision already accepts it by asking only for
stability across restarts *of the same deployment*.

Raised while grilling `autoregister_connectors` after wayfinder ticket #29, under map #24.
