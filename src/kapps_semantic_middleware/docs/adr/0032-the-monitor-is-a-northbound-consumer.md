# The monitor is a northbound consumer, not a wired instance

> **Coming soon — milestone 2. Nothing below runs today.**
>
> No monitor process exists. `demo/transferunits/launcher.py` starts PLCs, middleware
> instances and one control station, and nothing else. No `fac:MonitoringStation`
> individual is ever seeded.
>
> This record is a **design**, written before the code. Read every present-tense verb
> below as "the monitor will", not as "the monitor does". Milestone 1 ships the factory
> without it, and ADR 0029's 2026-07-31 amendment records why: build the minimum example,
> make it run, then add the monitor against working code.

The scenario 3 monitor does not wire a connector. It does not abstract a device. It reads the knowledge graph with
SPARQL, and it reads other middleware instances over REST. It holds two seams. It does not hold a third seam.

This answers wayfinder ticket #59, which offered three shapes. All three assumed a southbound bind
to each unit. The monitor does not bind to a unit. The library does not need a new shape.

## Two axes, and the word that confused them

**Connector wiring** describes how a device-facing instance connects to its device. The constructor
parameters are `autoregister_connectors` and `connector_sync_direction` (ADR 0020). This axis stays
valid and unchanged.

**Role** described what an instance exists for. **This axis is retired — see the amendment below.**
It rested on whether an instance had connector wiring, and ADR 0033 gives every instance connector
wiring. An instance is now described by its connector's **protocol** and **direction**, and by
nothing else.

The text this ADR originally carried, kept for the record:

> - **Resource middleware** — it abstracts one device. It is device-facing. It has a connector wiring.
> - **Consumer** — it does not abstract a device. It does not have connector wiring. It reads the
>   graph and other middleware instances over REST.

ADR 0020 named three connector wirings `controller`, `monitor` and `inspector`. Those names describe
products, and the columns beside them describe settings. The code contradicts the names.
`Controller.__init__` passes `autoregister_connectors=False` and `class_scope=None`, so the
controller occupies the `inspector` row. The monitor occupies the same row. This decision retires
the word "flavour", and ADR 0020 loses its product names.

## What the monitor shows

The monitor is the Launcher index page for a factory that runs. The Launcher draws its page
because it built the factory. The monitor derives every box from the graph. The purpose is the same,
and the lifecycle stage differs.

1. It queries resources of a class, and it attaches each resource's Service.
2. A row reads `live` when a Service carries `svc:address`. A row reads `offline` when a Service node
   carries no address, which is what the ADR 0007 watchdog leaves. A row reads `unmanaged` when no
   Service exists.
3. A collapsed row carries no data. The dashboard stays readable with many units.
4. An expand action queries that instance for its `svc:StateProperty` nodes and for the domain
   properties that are subproperties of `inf:isInterfaceAccessibleParameter`.
5. Each such attribute carries a refresh control. The control triggers one REST GET.

## The two seams

**The graph, with SPARQL.** Discovery and structure. Resources, Services, addresses, heartbeats,
workflows, state properties and interface-accessible parameters.

**The middleware REST surface.** Content. The monitor reads a live value over the recursive datamodel
routes of ADR 0017.

The monitor never calls `ogm.fetch` **for a value**. Two facts decide this, and ADR 0033 separates
them, because only one of them is an objection.

ADR 0024 puts scenario 3 on the locator pattern, so the graph holds no `inf:hasValue` literal, and a
graph fetch renders empty cells. **This is no obstacle to fetching structure** — an empty-slotted
skeleton is exactly what a connector should fill, and ADR 0033 builds on that.

`prune_southbound` also runs inside the instance that serves the data, so an OGM fetch returns the
unpruned specification. **This objection is real and stands.** An instance that fetches from the OGM
must repeat the northbound projection, or it holds the broker address. ADR 0028 exists to prevent
that. ADR 0033 discharges it by pruning at load time rather than by forbidding the fetch.

So the rule is sharper than the sentence above: **structure may come from the graph and must be
pruned; a value never comes from the graph.**

## The middleware is the interface boundary

The datamodel inside a middleware instance divides northbound from southbound. What the factory needs
crosses that boundary. What only the device needs stays behind it. A robot holds many joints, and the
factory wants the end effector position.

The ontology decides which parameters cross. The monitor displays what the ontology declares. The
monitor therefore shows no broker, no topic and no PLC. It shows middleware instances and the
resources they abstract.

## Two forms of one invariant

A monitor must never drive a device. This ADR originally held that two separate arguments were
needed, because the two roles were different:

> - **A device-facing observer** cannot drive, because it registers no `FROM_PERSISTENCE` connector
>   (ADR 0023).
> - **A consumer** cannot drive, because its own code holds no method that sends a PUT request.
>
> Neither argument covers the other case.

**ADR 0033 inverts this.** Once the monitor reaches its peers through a connector, the second
argument stops meaning anything — the PUT lives in the connector, not in the monitor's own code — and
the first argument covers both cases. The two arguments **unify**: an instance cannot drive when it
registers no write-direction connector, whether that connector faces a device or a peer.

The guard test follows the wiring rather than the source text. The demo keeps the original
no-PUT-method assertion as well, because it is cheap and it covers the UI path a connector guard does
not reach.

## Consequences

- The monitor lives in `demo/`, per **root ADR 0004**. It duplicates the discovery code rather
  than shares it.
- The monitor runs in resource mode over a `fac:MonitoringStation` individual, with `class_scope=None`.
  It registers its own Service, holds a heartbeat, and inherits the `/activity` feed. It appears in
  its own dashboard. *(This ADR originally also said `autoregister_connectors=False`. ADR 0033
  supersedes that: the monitor autoregisters REST connectors at an observing wiring, which is what
  makes it structurally unable to drive.)*
- The seed writes a second `fac:` individual for the monitoring station (ADR 0030).
- **#47 is no longer a prerequisite of the monitor.** The unit middleware roots at the unit, the
  controller at a control station, and the monitor at a monitoring station. No two instances share a
  resource in this demo. ADR 0022 stays valid for the general case, such as a redundant pair, or a
  restart before deregistration.
- ADR 0020 keeps its security argument by a shorter route. One unit middleware with
  `autoregister_connectors=False` leaks on its own, and the argument needs no second instance.
- The monitor does not aggregate a `/activity` feed. Each expanded row links to the feed of its own unit. A
  merged feed would collect every MQTT topic of the factory onto one page.
- Scenario 3 creates no `cfc:Operation`, so the dashboard shows no operation provenance.
- In code the `plan_wiring` and `resolve_direction` parameter becomes `sync_direction`. In prose the
  axis is "connector wiring".

Resolves wayfinder ticket #59 under map #57.

## Amendment, 2026-08-03, ticket #33

**What ADR 0033 changes here, and why.** This ADR was written for a monitor that reached its peers
with direct HTTP calls. Ticket #33 asked the same question of the controller and got a different
answer: a consumer reaches a peer *through a connector*, because a peer middleware's REST surface is
a protocol like any other. Four claims above do not survive that.

**The role axis is retired.** `Resource middleware` versus `Consumer` rested on whether an instance
had connector wiring. Every instance now has connector wiring, so the distinction distinguishes
nothing. An instance is described by its connector's **protocol** and **direction**. The `Role` entry
leaves `CONTEXT.md`; **Connector wiring** stays and becomes the only axis, extended with protocol.
The two facts the Role entry carried that were never about roles — that the controller and the
monitor each root at their own station resource and register a Service, and that neither registers a
Workflow so an Operation never resolves to one (ADR 0002) — move into the demo's own `CONTEXT.md`,
where they describe the two stations rather than a role.

**The two non-driving arguments unify** rather than staying separate. See the section above.

**`ogm.fetch` is permitted for structure** and forbidden for values, rather than forbidden outright.
The locator half of the original objection was never an objection; the projection half is discharged
by pruning at load time.

**ADR 0020's three wirings become accurate.** This ADR observed that `Controller.__init__` passes
`autoregister_connectors=False` and therefore sat in the *inspecting* row while being called a
controller, and it treated that as evidence the names were wrong. Under ADR 0033 the controller is
genuinely **driving**, the monitor genuinely **observing**, and the unit middleware **driving**. The
names were right; the code had not caught up.

**What stands unchanged.** Everything this ADR decided about *what the monitor shows* — resources
first with Services attached, the three row states, a collapsed row carrying no data, expand querying
`svc:StateProperty` and the subproperties of `inf:isInterfaceAccessibleParameter`, a refresh control
per attribute, no aggregated `/activity` feed, no operation provenance — is untouched. So is "the
middleware is the interface boundary", which ADR 0033 leans on rather than revises. So is the finding
that #47 is not a prerequisite.
