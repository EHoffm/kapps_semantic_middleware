"""Scenario 3: a TransferUnit driven over MQTT — the graph wires the connectors.

A debugger-friendly, plain-Python walkthrough of the mock PLC → middleware → controller loop
(map #24). Where scenario 1 demonstrates operation coordination and scenario 2 direct
workflow invocation, this one demonstrates **ontology-driven wiring**: nothing in this file
names a topic or a broker. The middleware reads the seeded TransferUnit out of the knowledge
graph, works out that four of its properties are interface-accessible parameters, and builds
six MQTT connectors pointed at the addresses the graph gave it.

The device end is deliberately dumb. ``MockTransferUnit`` speaks MQTT and knows nothing about
the graph, the ontology, or the middleware — which is the asymmetry the scenario exists to
show.

Run from a debugger or as a script. The numbered functions are convenient breakpoints.

Prerequisites: the ``GRAPHDB_*`` environment variables, and an MQTT broker on 127.0.0.1:1883.
If nothing is listening there, the script starts a pure-Python one for its own lifetime and
says so, so it runs on a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket

from graph_db_interface import GraphDB
from kapps_ogm import OGM
from kapps_ogm.utils.class_scope import ClassScope

from aas_middleware.middleware.sync.synced_connector import SyncDirection
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.connectors.semantic import default_registry
from kapps_semantic_middleware.projection import carries_southbound
from kapps_semantic_middleware.vocabulary import INF

import seed
from mock_transferunit import MockTransferUnit

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
UNIT_PORT = 8996
SETPOINT = 2.5


def transfer_unit_view() -> ClassScope:
    """The consumer's view of a TransferUnit: the unit, its components, their parameters.

    Two levels, because a TransferUnit's parameters hang off its belts and barriers. A view
    belongs to its consumer and is configured here in embedding code rather than in the
    ontology (ADR 0018) — the ontology cannot know how deep any particular consumer cares to
    look.
    """
    return ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )


def _broker_is_running() -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((BROKER_HOST, BROKER_PORT)) == 0


@contextlib.asynccontextmanager
async def _broker():
    """Use the broker already on 1883, or run one in-process for this script's lifetime."""
    if _broker_is_running():
        print(f"Using the MQTT broker already listening on {BROKER_HOST}:{BROKER_PORT}")
        yield
        return

    from amqtt.broker import Broker

    print(f"No broker on {BROKER_HOST}:{BROKER_PORT} — starting an in-process one")
    broker = Broker(
        {
            "listeners": {
                "default": {"type": "tcp", "bind": f"{BROKER_HOST}:{BROKER_PORT}"}
            },
            "sys_interval": 0,
            "auth": {"allow-anonymous": True},
            "topic-check": {"enabled": False},
        }
    )
    await broker.start()
    try:
        yield
    finally:
        await broker.shutdown()


def step_1_seed_clean_repository(db: GraphDB) -> None:
    """Clear the repository and create the TransferUnit, two belts and two barriers.

    Everything goes through ``ogm.create`` — the same validated write path a running
    middleware uses (root ADR 0008). The ontology file itself is classes only.
    """
    print("\nStep 1 — Seed a Clean Repository")
    seed.seed_scenario3(db, OGM(db=db))

    for iri in (
        seed.CONVEYOR_BELT_LEFT,
        seed.CONVEYOR_BELT_RIGHT,
        seed.LIGHT_BARRIER_FRONT,
        seed.LIGHT_BARRIER_BACK,
    ):
        print(f"  component created: {str(iri).split('#')[-1]}")

    # The metadata is in the graph, and it is the only place any topic is written down.
    rows = db.query(
        f"SELECT ?t FROM <http://www.ontotext.com/explicit> WHERE {{ ?n <{INF.hasMQTTTopic}> ?t }}",
        convert_bindings=True,
    )["results"]["bindings"]
    print(f"  topics recorded in the graph: {len(rows)}")


def step_2_start_the_middleware(db: GraphDB) -> SemanticMiddleware:
    """Construct the TransferUnit middleware — wiring happens here, not on startup.

    Passing a ``class_scope`` is what asks for the parameters under it to be wired. The
    constructor resolves them from the ClassSpec and the graph and registers the connectors
    immediately, because ``lifespan`` connects everything in the registry *before* running
    startup callbacks — a connector registered later never connects, and its inbound
    direction dies silently (ADR 0023).
    """
    print("\nStep 2 — Construct the Middleware (connectors are wired in the constructor)")
    unit = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.TRANSFER_UNIT_1,
        service_class=f"{seed.TU_NS}TransferUnitService",
        ogm=OGM(db=db),
        host="127.0.0.1",
        port=UNIT_PORT,
        class_scope=transfer_unit_view(),
        # The controller flavour: reads live values and may drive the device. A monitor
        # passes connector_sync_direction=TO_PERSISTENCE; an inspector passes
        # autoregister_connectors=False (ADR 0022).
        connector_sync_direction=SyncDirection.BIDIRECTIONAL,
    )
    print(f"  registry knows {len(default_registry)} binding descriptor(s)")
    print(f"  connectors registered before startup: {bool(unit.connection_registry.connections)}")
    return unit


def step_3_inspect_what_recognition_found(unit: SemanticMiddleware) -> None:
    """Four parameters, four bindings, six connectors, six topics — all from the graph."""
    print("\nStep 3 — What Recognition Found")
    plan = unit._wiring

    print(f"  parameters recognised: {len(plan.bindings)}")
    for binding in plan.bindings:
        print(
            f"    {str(binding.resource_iri).split('#')[-1]:22}"
            f" {str(binding.parameter_property).split('#')[-1]:18}"
            f" accessMode={binding.access_mode}"
        )

    print(f"  connectors built: {len(plan.registrations)}")
    for _, registration in plan.registrations:
        direction = (
            "read " if registration.sync_direction is SyncDirection.TO_PERSISTENCE else "write"
        )
        print(f"    {direction}  {registration.connector.topic}")

    # A settable parameter needs two connectors: MqttClientConnector publishes where it
    # subscribed, so a read topic and a set topic cannot share one instance (ADR 0023).
    print("  (4 parameters -> 4 bindings -> 6 connectors: the two belts are settable)")


def step_4_show_the_northbound_projection(unit: SemanticMiddleware) -> None:
    """The served payload carries the value, unit and access mode — and no way to reach the device.

    The connection metadata is not filtered out of the data; it is removed from the *shape*
    before anything is fetched, so the northbound model has no field to carry a broker address
    in (ADR 0028).
    """
    print("\nStep 4 — The Northbound Projection")
    plan = unit._wiring

    node = unit.ogm.fetch(
        instance_iri=seed.TRANSFER_UNIT_1, **plan.northbound_fetch_kwargs()
    )
    served = node.instance.model_dump()

    belt = served[seed.TU_HAS_CONVEYOR_BELT.lined][0]
    parameter = belt[seed.TU_HAS_CONVEYOR_SPEED.lined][0]
    print("  a belt's speed parameter, as a peer would receive it:")
    for field, value in parameter.items():
        print(f"    {field.split('_h_')[-1]:16} = {value}")

    leaks = carries_southbound(served, plan.southbound_properties)
    print(f"  connection metadata present in the served payload: {leaks or 'none'}")
    assert not leaks, "a broker address reached the northbound payload"
    assert seed.MQTT_BROKER_IP not in str(served)


async def step_5_read_a_live_value(unit: SemanticMiddleware, plc: MockTransferUnit) -> None:
    """The mock PLC publishes a speed; the connector the graph built receives it."""
    print("\nStep 5 — A Live Value Flows Device -> Middleware")
    read = _registration(unit, "ConveyorBelt/left/speed", SyncDirection.TO_PERSISTENCE)

    await read.connector.connect()
    try:
        value = await asyncio.wait_for(read.connector.queue.get(), timeout=10.0)
        print(f"  received on {read.connector.topic}: {value}")

        # The formatter rebuilds the whole parameter node, not just the value: setattr
        # replaces the node wholesale and the formatter sees only the payload, so a bare
        # scalar would blank the unit in the model that is served over REST.
        [node] = read.formatter.deserialize(value)
        print(f"    -> value      {getattr(node, INF.hasValue.lined)}")
        print(f"    -> unit kept  {getattr(node, seed.TU_HAS_UNIT.lined)}")
        print(f"    -> mode kept  {getattr(node, INF.accessMode.lined)}")
    finally:
        await read.connector.disconnect()


async def step_6_drive_the_device(unit: SemanticMiddleware, plc: MockTransferUnit) -> None:
    """A setpoint written through the middleware moves the mock PLC, which reports back."""
    print("\nStep 6 — A Setpoint Flows Middleware -> Device")
    write = _registration(unit, "ConveyorBelt/left/speed_set", SyncDirection.FROM_PERSISTENCE)
    read = _registration(unit, "ConveyorBelt/left/speed", SyncDirection.TO_PERSISTENCE)

    print(f"  belt speed before: {plc.speeds['left']}")
    await read.connector.connect()
    await write.connector.connect()
    try:
        # Exactly the path the sync machinery takes: persistence value -> formatter ->
        # connector.consume.
        [node] = write.formatter.deserialize(SETPOINT)
        payload = write.formatter.serialize([node])
        print(f"  publishing {json.loads(payload)} to {write.connector.topic}")
        await write.connector.consume(payload)
        await plc.wait_for_setpoint(timeout=10.0)
        print(f"  belt speed after:  {plc.speeds['left']}")

        async def until_setpoint_reported():
            while True:
                if await read.connector.queue.get() == SETPOINT:
                    return SETPOINT

        reported = await asyncio.wait_for(until_setpoint_reported(), timeout=10.0)
        print(f"  device reported it back on {read.connector.topic}: {reported}")
    finally:
        await write.connector.disconnect()
        await read.connector.disconnect()

    assert plc.speeds["left"] == SETPOINT


async def step_7_a_read_only_sensor(unit: SemanticMiddleware, plc: MockTransferUnit) -> None:
    """A light barrier is read-only, and the middleware has no way to drive it."""
    print("\nStep 7 — A Read-Only Parameter")
    read = _registration(unit, "LightBarrier/front/occupied", SyncDirection.TO_PERSISTENCE)

    writable = [
        r
        for _, r in unit._wiring.registrations
        if "occupied" in r.connector.topic
        and r.sync_direction is SyncDirection.FROM_PERSISTENCE
    ]
    print(f"  write connectors built for the barriers: {len(writable)}")
    assert not writable, "a read-only sensor must have no write connector"

    await read.connector.connect()
    try:
        await asyncio.sleep(0.3)
        await plc.set_occupied("front", True)

        async def until_occupied():
            while True:
                if await read.connector.queue.get() is True:
                    return True

        await asyncio.wait_for(until_occupied(), timeout=10.0)
        print(f"  barrier tripped, observed on {read.connector.topic}: True")
    finally:
        await read.connector.disconnect()


def step_8_the_value_is_never_persisted(db: GraphDB) -> None:
    """Scenario 3 is a locator: the graph says where the value lives, never what it is."""
    print("\nStep 8 — The Live Value is Never Persisted (ADR 0024)")
    rows = db.query(
        f"SELECT ?v FROM <http://www.ontotext.com/explicit> WHERE {{ ?n <{INF.hasValue}> ?v }}",
        convert_bindings=True,
    )["results"]["bindings"]
    print(f"  inf:hasValue literals in the graph: {len(rows)}")
    assert not rows, "the live value must not be written to the graph"


def _registration(unit: SemanticMiddleware, topic_suffix: str, direction: SyncDirection):
    """The registration the graph produced for one topic, found by suffix rather than by name."""
    for _, registration in unit._wiring.registrations:
        if registration.connector.topic.endswith(topic_suffix) and (
            registration.sync_direction is direction
        ):
            return registration
    raise AssertionError(f"no {direction.name} connector for a topic ending {topic_suffix!r}")


async def main() -> None:
    """Run the complete Scenario 3 lifecycle."""
    db = GraphDB.from_env()
    print(f"Connected to GraphDB repository: {os.getenv('GRAPHDB_REPOSITORY')}")

    async with _broker():
        step_1_seed_clean_repository(db)
        unit = step_2_start_the_middleware(db)
        step_3_inspect_what_recognition_found(unit)
        step_4_show_the_northbound_projection(unit)

        async with MockTransferUnit(
            broker=BROKER_HOST, port=BROKER_PORT, publish_interval=0.2
        ) as plc:
            print(
                f"\nMock PLC up — publishing {len(plc.published_topics)},"
                f" subscribed to {len(plc.subscribed_topics)}"
            )
            await step_5_read_a_live_value(unit, plc)
            await step_6_drive_the_device(unit, plc)
            await step_7_a_read_only_sensor(unit, plc)

        step_8_the_value_is_never_persisted(db)

    print("\nScenario 3 complete.")


if __name__ == "__main__":
    asyncio.run(main())
