# The monitor is a northbound consumer, not a wired instance

The scenario 3 monitor does not wire a connector. It does not abstract a device. It reads the knowledge graph with
SPARQL, and it reads other middleware instances over REST. It holds two seams. It does not hold a third seam.

This answers wayfinder ticket #59, which offered three shapes. All three assumed a southbound bind
to each unit. The monitor does not bind to a unit. The library does not need a new shape.

## Two axes, and the word that confused them

**Connector wiring** describes how a device-facing instance connects to its device. The constructor
parameters are `autoregister_connectors` and `connector_sync_direction` (ADR 0020). This axis stays
valid and unchanged.

**Role** describes what an instance exists for. Two roles exist:

- **Resource middleware** — it abstracts one device. It is device-facing. It has a connector wiring.
- **Consumer** — it does not abstract a device. It does not have connector wiring. It reads the graph and other
  middleware instances over REST.

The controller and the monitor are consumers. The unit middleware is a resource middleware.

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

The monitor never calls `ogm.fetch` for a value. Two facts decide this. ADR 0024 puts scenario 3 on
the locator pattern, so the graph holds no `inf:hasValue` literal, and a graph fetch renders empty
cells. `prune_southbound` also runs inside the instance that serves the data, so an OGM fetch returns
the unpruned specification. A monitor that fetches from the OGM must repeat the northbound
projection, or it renders the broker address. ADR 0028 exists to prevent that.

## The middleware is the interface boundary

The datamodel inside a middleware instance divides northbound from southbound. What the factory needs
crosses that boundary. What only the device needs stays behind it. A robot holds many joints, and the
factory wants the end effector position.

The ontology decides which parameters cross. The monitor displays what the ontology declares. The
monitor therefore shows no broker, no topic and no PLC. It shows middleware instances and the
resources they abstract.

## Two forms of one invariant

A monitor must never drive a device. The demonstration now needs two separate arguments, because the
two roles are different.

- **A device-facing observer** cannot drive, because it registers no `FROM_PERSISTENCE` connector
  (ADR 0023).
- **A consumer** cannot drive, because its own code holds no method that sends a PUT request.

Neither argument covers the other case. A guard test in the demo asserts the second one.

## Consequences

- The monitor lives in `demo/`, per **root ADR 0004**. It duplicates the discovery code rather
  than shares it.
- The monitor runs in resource mode over a `fac:MonitoringStation` individual, with `class_scope=None`
  and `autoregister_connectors=False`. It registers its own Service, holds a heartbeat, and inherits
  the `/activity` feed. It appears in its own dashboard.
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
