# The connector seam carries REST, and a peer middleware is a device

A middleware instance reaches another middleware instance the same way it reaches a PLC: through a
connector, recognised from the graph, driven by the synchronization layer. The protocol differs. The
seam does not.

This answers wayfinder ticket #33 under map #57, and it replaces the ad-hoc HTTP calls #43 shipped.

## Two experts, and the only thing they share

The demonstration is not a factory. It is two domain experts who never meet.

**The TransferUnit Expert** builds the machine. They speak belts, barriers, PLCs and MQTT. They
configure a middleware for their product, and that middleware reads the unit's description out of the
graph, wires its connectors from what it finds, serves the datamodel over the ADR 0017 routes, and
publishes its own address. At that point the unit is discoverable, addressable and drivable
factory-wide, and **this expert's job is finished**. They have never heard of a routing algorithm and
they do not need to.

**The Control Expert** is one of twenty. They are a professional at routing algorithms and material
flow control. They know the TransferUnit ontology. They know nothing about any particular unit, its
broker, or its address. Their work is five steps:

1. **A view, written as a SPARQL query.** Every live TransferUnit, narrowed by whatever heuristic the
   algorithm needs — an area of the plant, a topology, or in this demo, an even unit index. Live means
   the resource's Service carries an `svc:address`.
2. **A fetch per hit.** `ogm.fetch` returns the structure. ADR 0024 puts scenario 3 on the locator
   pattern, so the graph holds no `inf:hasValue`, and what comes back is exactly the empty-slotted
   skeleton a connector should fill.
3. **A load into their own instance.** N datamodels, one per unit under control. The scope roots at
   each `tu:TransferUnit`, not at the control station — which is why no station-to-units property is
   needed, and why the graph's silence about plant layout costs nothing here.
4. **An algorithm against objects.** Read a barrier, set a speed. No HTTP, no topic, no IRI in the
   algorithm's body.
5. **There is no step five.** The assignment is the whole interface.

**The knowledge graph is the entire contract.** One expert publishes reachability into it; the other
queries reachability out of it. Neither imports the other's code.

## The decision

**A REST binding descriptor, beside the MQTT one.** `connectors/rest_binding.py` in the library,
`connectors/mqtt_binding.py`'s exact sibling: one binding descriptor per protocol. It satisfies the
same `Provider` and `Consumer` protocols, and it names a `connector_cls` the way ADR 0023 requires.

**Recognition joins through the Service.** An MQTT connector recognises `inf:hasMQTTTopic` on the
parameter. A REST connector has no such marker and needs none. Its evidence is that the parameter is
interface-accessible and the resource's Service carries an `svc:address`. That is still recognition
from the graph — it joins one hop further out. ADR 0023 is amended to say so.

**Pruning makes recognition unambiguous.** A fetched spec carries the unit's MQTT markers, because
`seed.py` writes them into the graph as real parameter metadata. An instance that loaded such a spec
unpruned would both hold the factory's broker addresses and match MQTT recognition on a device it has
no business touching. Pruning on load removes the markers, so MQTT recognition matches nothing and the
Service-joined rule is the only one left. The two mechanisms interlock: neither is safe without the
other.

**The route is structural, so nothing else is needed.** ADR 0017 made route paths mirror the datamodel
tree, precisely so a consumer derives every parameter URL from a single GET. Address plus structural
path is a complete binding. No ontology term is added, and this work does not gate on #39.

**Direction comes from the same rule as MQTT.** The most restrictive of `inf:accessMode` and the
instance's connector wiring, per ADR 0023. A parameter at `readwrite` under a driving wiring binds
bidirectionally. The same parameter under an observing wiring binds read-only.

## Consequences

- **The three connector wirings become accurate.** ADR 0032 complained that
  `Controller.__init__` passes `autoregister_connectors=False` and therefore occupied ADR 0020's
  *inspecting* row while being named a controller. It now genuinely occupies **driving**, the monitor
  occupies **observing**, and the unit middleware occupies **driving**. The contradiction is fixed
  rather than renamed.
- **The role axis is gone.** ADR 0032's `Resource middleware` / `Consumer` split rested on whether an
  instance had connector wiring, which is now false of every instance. An instance is described by its
  connector's protocol and direction, and by nothing else. See ADR 0032 as amended.
- **Pruning moves to load time, and becomes visible.** `prune_southbound` already takes a bare
  `(class_spec, *, ogm)` and is callable outside a serving instance. Loading a fetched datamodel runs
  it, so an expert who has never heard of southbound metadata cannot leak it, and an unknown protocol
  is still excluded because the delete set comes from the ontology. What was removed is exposed rather
  than silent — the boundary is the thing this demo teaches, and a projection nobody can see teaches
  nothing.
- **Consumers inherit #61's dependency.** The serving path already needed the interface ontology
  present in the store. Pruning on load extends that to any instance that loads a fetched datamodel.
- **#43's HTTP methods are demoted.** `open_resource`, `get_parameter` and `set_parameter` become the
  connector's internals or they go. `discover_resources` and `_build_parameter_path` survive — every
  option needed discovery and structural path derivation.
- **#69 stops being optional.** See ADR 0029 as amended: a per-unit broker is impossible without
  `inf:hasMQTTBrokerPort`, so #69 is a hard prerequisite of milestone 1 rather than a convenience.
- **Root ADR 0004 is amended** so this lands in `src/` rather than `demo/`. A protocol mechanism the
  middleware itself defines is generic at birth.

## What this does not decide

**The parameter node is not a scalar, and the algorithm sees that.** ADR 0027 skolemises a parameter
node carrying `inf:hasValue`, `inf:hasUnit` and `inf:accessMode`, and ADR 0017's payload is a list of
those dicts. So step 4's `unit.conveyor_belt_left.speed = 12.4` is really
`unit.conveyor_belt_left.speed[0]["inf:hasValue"][0] = 12.4`. Accepted as it stands. Whether a
domain expert should be handed something more ergonomic is a separate question, and it is not this
ADR's.

**A material flow controller is not built here.** The English term for the *Materialflussrechner* the
Control Expert stands in for — an algorithm that routes parcels across units by reading barriers and
deciding which unit to trigger — names the kind of thing that could be wired to this interface. This
demo wires a deliberately meaningless algorithm instead, because building a real one is domain work,
not middleware work. The graph carries no plant layout, so nothing here can route anything, and that
is the MVP boundary rather than an oversight.

**One client per instance per broker** stays #70's. **The controller's own UI** is specified
separately.

Resolves wayfinder ticket #33 under map #57.
