# The factory's identity is its unit index

The launcher seeds N identical TransferUnits. Every IRI and every MQTT topic is a pure function
of the unit index. No registry file and no random identifier exists. The launcher refuses to
clear a graph that holds a factory that already runs.

ADR 0029 gave the launcher the seed, because the launcher decides N. This ADR fixes what the
launcher writes.

## The index is the identity

```
tui: = https://www.sfb1574.kit.edu/ontologies/TransferUnitInstances#

n = 1..N
    tui:TransferUnit<n>
    tui:ConveyorBelt<n>_left      tui:ConveyorBelt<n>_right
    tui:LightBarrier<n>_front     tui:LightBarrier<n>_back
```

Unit 1 keeps the IRIs that `examples/seed.py` writes today. ADR 0015, ADR 0017, ADR 0022 and
`../mqtt-payloads.md` quote those IRIs, and they stay correct.

A restart mints the same IRI for the same unit, because the index is the only input. A run with
`--units 3` after a run with `--units 2` leaves units 1 and 2 unchanged. The graph collects no
orphan.

A launcher-side registry file was the alternative. It buys opaque identifiers and it costs
restart stability, because a lost file orphans a whole factory.

## The topic scheme is unchanged

ADR 0023 fixed `TransferUnit<n>/<component>/<position>/<param>`, and a setpoint appends `_set`.
That scheme already carries the unit index in its first segment, so two units in one factory
cannot collide.

A factory-level topic prefix was considered and rejected. Two factories on one broker collide,
and the answer to that is to not do it. The demo runs a local broker, and the launcher's fixed
port stops a second launcher on the same host.

## The launcher probes before it clears

The seed clears the default graph. With N units, a controller and a monitor on one graph, a
clear is a whole-factory operation.

The launcher's fixed port looks like a mutex, but it is not one. The launcher spawns its
children as separate processes. A `kill -9` on the launcher leaves the children alive and frees
the port. A second launcher run then wipes the graph under N live middleware instances.

So the launcher asks the graph first. A factory is live when any node carries `svc:address` and
a `svc:lastHeartbeat` inside the ADR 0007 staleness window. This is the inverse of
`find_stale_services` in `registration.py`, so the rule already exists in SPARQL.

- A live factory aborts the run, and the message names the units.
- `--force` clears anyway.
- Stale nodes from a crash are not live, so the ordinary rerun after a crash needs no flag.

## What the seed writes, beyond the units

#43 makes the controller a resource-mode planner with its own `cfc:Resource` class and
`svc:Service` class. The controller appears in its own discovery list. No such class exists
today.

`demo/transferunits/factory.ttl` declares them, in a namespace the demo owns:

```turtle
fac:ControlStation        rdfs:subClassOf cfc:Resource .
fac:ControlStationService rdfs:subClassOf svc:Service .
```

The monitor's classes land in the same file in milestone 2. The `tu:` module stays the sfb1574
device vocabulary, and a control station is not a device.

The launcher seeds one control station individual. The launcher manufactures the initial
situation, and the controller is part of that situation.

## Where the code lives

`demo/transferunits/` is a real Python package. ADR 0029 wrote the directory as
`demo/TransferUnits/` and the runner as `python -m demo.transferunits.middleware`. Those two
disagree, and the copy-pasteable command line is the one that must work.

`clear_repository` and `load_shared_ontologies` move into
`src/kapps_semantic_middleware/seeding.py`. They load `core.ttl`, `service.ttl` and `mes.ttl`
out of the installed package, so they are library code that sits in `examples/` today.
`examples/seed.py` imports them, and scenarios 1 and 2 see no change. #61 lands in the same
module.

The unit shape stays outside the library. ADR 0021 forbids a domain IRI in the middleware core.

## The factory lives in the default graph

Every scenario runs against a dedicated, clearable repository (examples ADR 0001). The default
graph of that repository holds the factory and nothing else. Core, `svc:` and `mes:` sit in
named graphs of their own, and the clear leaves them.

One named graph for the whole factory is the tidier end state, and #46 asks for it. It was
rejected for milestone 1. `SemanticMiddleware` accepts a `named_graph` argument, but no test
exercises that read path across N processes. Milestone 1 exists to make the demo run.

## Consequences

- **`seed_scenario3` freezes.** Five test files depend on it and on the single-unit constants.
  They are the regression net for the connector work and the routing work.
  `demo/transferunits/seed.py` is written fresh. ADR 0029 already retires scenario 3 when the
  factory lands, so the duplication ends in its own commit.
- **Every unit is identical in milestone 1.** Two conveyor belts and two light barriers, the
  sfb1574 shape. Unit-shape variation defers behind #35, together with the runtime provisioning
  path of #54. Differing units stress the recognition path, and that question deserves a running
  demo rather than a unit test.
- **`--units N` defaults to 2**, and no upper bound applies.
- **The MQTT broker address gains a port.** ADR 0031 records that decision and its cost.

Decided on wayfinder ticket #60, under map #57. Amends ADR 0029 on the directory name.
