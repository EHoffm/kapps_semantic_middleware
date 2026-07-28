"""Self-contained seeding for the example scenarios (ADR 0010).

Every example scenario runs against a dedicated, clearable GraphDB repository.
These helpers clear it and load exactly the ground-truth ontology the scenario
needs (the ``svc:`` module plus the scenario's own demo ontology), then create
the starting instance data — so a scenario notebook or integration test is a
complete, reproducible specification of its own prerequisites and never depends
on production state.

Everything is written into the repository's default graph, which
``clear_repository`` wipes at the start of each run.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from typing import Optional

from graph_db_interface import IRI
from kapps_ogm.utils.class_scope import ClassScope
from rdflib.namespace import RDF

from kapps_semantic_middleware.registration import create_possession
from kapps_semantic_middleware.vocabulary import MES


DEMO_NS = "https://example.org/kapps-demo#"

# --- Scenario 1 class IRIs (ground-truth, declared in demo_ontology.ttl) ---
HELLO_RESOURCE_CLASS = IRI(f"{DEMO_NS}DemoResource")
HELLO_SERVICE_CLASS = IRI(f"{DEMO_NS}HelloWorldService")
HELLO_CAPABILITY_CLASS = IRI(f"{DEMO_NS}HelloWorldCapability")
HELLO_WORKFLOW_CLASS = IRI(f"{DEMO_NS}HelloWorldWorkflow")
PLANNER_RESOURCE_CLASS = IRI(f"{DEMO_NS}PlannerResource")
PLANNER_SERVICE_CLASS = IRI(f"{DEMO_NS}PlannerService")

# --- Scenario 1 instance IRIs ---
HELLO_RESOURCE = IRI(f"{DEMO_NS}hello_resource")
PLANNER_RESOURCE = IRI(f"{DEMO_NS}planner_resource")

# --- Scenario 2 (door) class IRIs ---
DOOR_RESOURCE_CLASS = IRI(f"{DEMO_NS}DoorResource")
DOOR_SERVICE_CLASS = IRI(f"{DEMO_NS}DoorControllerService")
DOOR_OPEN_CAPABILITY_CLASS = IRI(f"{DEMO_NS}DoorOpenCapability")
DOOR_CLOSE_CAPABILITY_CLASS = IRI(f"{DEMO_NS}DoorCloseCapability")
DOOR_STATUS_CAPABILITY_CLASS = IRI(f"{DEMO_NS}DoorStatusCapability")
DOOR_OPEN_WORKFLOW_CLASS = IRI(f"{DEMO_NS}DoorOpenWorkflow")
DOOR_CLOSE_WORKFLOW_CLASS = IRI(f"{DEMO_NS}DoorCloseWorkflow")
DOOR_STATUS_STATE_CLASS = IRI(f"{DEMO_NS}DoorStatusStateProperty")

# --- Scenario 2 instance IRIs ---
DOOR_RESOURCE = IRI(f"{DEMO_NS}door_042")

# Mobile robot (scenario 2 consumer): discovers and drives the door through the graph.
MOBILE_ROBOT_RESOURCE_CLASS = IRI(f"{DEMO_NS}MobileRobotResource")
MOBILE_ROBOT_SERVICE_CLASS = IRI(f"{DEMO_NS}MobileRobotControllerService")
MOBILE_ROBOT = IRI(f"{DEMO_NS}mobile_robot_007")

# --- Handover scenario IRIs (Core reified possession + mes: handover ability) ---
TRANSFER_MODULE_CLASS = IRI(f"{DEMO_NS}TransferModule")
BOX_CLASS = IRI(f"{DEMO_NS}Box")
HANDOVER_SOURCE = IRI(f"{DEMO_NS}transfer_module_A")
HANDOVER_DEST = IRI(f"{DEMO_NS}transfer_module_B")
HANDOVER_BOX = IRI(f"{DEMO_NS}box_001")

# --- Shared ontology named graphs -------------------------------------------------
# Core and svc: are needed by every scenario and never change during a run, so they
# live in named graphs of their own rather than being re-imported into the default
# graph each time. ``clear_repository`` clears only the default graph, so a seed wipes
# the scenario's own data and leaves these standing. GraphDB reasons across all graphs,
# so a domain class still resolves its cfc: superclass from here.
CORE_GRAPH = IRI("https://w3id.org/circularfactory/Core")
SERVICE_GRAPH = IRI("https://w3id.org/circularfactory/Service")
MES_GRAPH = IRI("https://w3id.org/circularfactory/MES")

# --- Scenario 3 (TransferUnit) ----------------------------------------------------
TU_NS = "https://www.sfb1574.kit.edu/ontologies/TransferUnit#"
TUI_NS = "https://www.sfb1574.kit.edu/ontologies/TransferUnitInstances#"
INF_NS = "https://www.sfb1574.kit.edu/ontologies/CrcInterfaces#"

TRANSFER_UNIT_CLASS = IRI(f"{TU_NS}TransferUnit")
CONVEYOR_BELT_CLASS = IRI(f"{TU_NS}ConveyorBelt")
LIGHT_BARRIER_CLASS = IRI(f"{TU_NS}LightBarrier")

TU_HAS_CONVEYOR_BELT = IRI(f"{TU_NS}hasConveyorBelt")
TU_HAS_LIGHT_BARRIER = IRI(f"{TU_NS}hasLightBarrier")
TU_HAS_CONVEYOR_SPEED = IRI(f"{TU_NS}hasConveyorSpeed")
TU_IS_OCCUPIED = IRI(f"{TU_NS}isOccupied")
TU_HAS_UNIT = IRI(f"{TU_NS}hasUnit")

INF_HAS_VALUE = IRI(f"{INF_NS}hasValue")
INF_ACCESS_MODE = IRI(f"{INF_NS}accessMode")
INF_HAS_MQTT_TOPIC = IRI(f"{INF_NS}hasMQTTTopic")
INF_HAS_MQTT_SET_TOPIC = IRI(f"{INF_NS}hasMQTTSetTopic")
INF_HAS_MQTT_BROKER_IP = IRI(f"{INF_NS}hasMQTTBrokerIP")

TRANSFER_UNIT_1 = IRI(f"{TUI_NS}TransferUnit1")
CONVEYOR_BELT_LEFT = IRI(f"{TUI_NS}ConveyorBelt1_left")
CONVEYOR_BELT_RIGHT = IRI(f"{TUI_NS}ConveyorBelt1_right")
LIGHT_BARRIER_FRONT = IRI(f"{TUI_NS}LightBarrier1_front")
LIGHT_BARRIER_BACK = IRI(f"{TUI_NS}LightBarrier1_back")

MQTT_BROKER_IP = "127.0.0.1"


def _read_core_ontology() -> str:
    """Return the vendored cfc: Core ontology Turtle.

    A verbatim copy of the published Core (version 0.9.0,
    https://circularfactory.github.io/Core/latest/ontology.ttl). Core is external and
    superior: imported and specialized, never modified (Core Middleware ADR 0012). It is
    vendored rather than fetched so seeding stays reproducible offline, matching the
    self-containment rule in examples ADR 0001.
    """
    return (
        resources.files("kapps_semantic_middleware")
        .joinpath("ontology", "core.ttl")
        .read_text(encoding="utf-8")
    )


def _read_service_ontology() -> str:
    """Return the packaged ``svc:`` ontology Turtle."""
    return (
        resources.files("kapps_semantic_middleware")
        .joinpath("ontology", "service.ttl")
        .read_text(encoding="utf-8")
    )


def _read_demo_ontology(filename: str) -> str:
    """Return a scenario demo ontology Turtle file (sibling of this file)."""
    return (Path(__file__).parent / filename).read_text(encoding="utf-8")


def clear_repository(db) -> None:
    """Clear the repository's default graph (authorized clearable test repo).

    Always run this before seeding, so a scenario never accumulates residual
    triples from a previous run or a different scenario.
    """
    db.clear_graph()


def load_shared_ontologies(db, *, reload: bool = False) -> None:
    """Load the published/general ontology modules, one named graph per ontology.

    Core, ``svc:`` and ``mes:`` are needed by every scenario and never change during a
    run, so each gets its own named graph rather than being re-imported into the default
    graph on every seed. ``clear_repository`` clears only the default graph, so a seed
    wipes the scenario's own data and leaves these standing; GraphDB reasons across all
    graphs, so a domain class still resolves its ``cfc:`` superclass from here.

    Idempotent: a module already present is skipped unless ``reload`` is set.
    """
    for graph, turtle in (
        (CORE_GRAPH, _read_core_ontology()),
        (SERVICE_GRAPH, _read_service_ontology()),
        (MES_GRAPH, _read_mes_ontology()),
    ):
        if reload:
            db.clear_graph(graph)
        elif _graph_is_populated(db, graph):
            continue
        db.import_statements(
            turtle, graph_iri=graph, content_type="application/x-turtle"
        )


def _graph_is_populated(db, graph_iri: IRI) -> bool:
    """Whether a named graph already holds any statement."""
    return bool(
        db.query(f"ASK {{ GRAPH <{graph_iri}> {{ ?s ?p ?o }} }}").get("boolean", False)
    )


def load_scenario1_ontologies(db) -> None:
    """Load the shared modules plus ONLY the scenario 1 demo classes."""
    load_shared_ontologies(db)
    db.import_statements(
        _read_demo_ontology("demo_scenario1.ttl"), content_type="application/x-turtle"
    )


def load_scenario2_ontologies(db) -> None:
    """Load the shared modules plus ONLY the scenario 2 (door) demo classes."""
    load_shared_ontologies(db)
    db.import_statements(
        _read_demo_ontology("demo_scenario2.ttl"), content_type="application/x-turtle"
    )


def load_scenario3_ontologies(db) -> None:
    """Load the shared modules plus the scenario 3 TransferUnit classes.

    ``transferunit.ttl`` is classes only — the ``inf:`` interface vocabulary and the
    ``tu:`` domain terms. Its instances are created through the OGM by
    :func:`seed_scenario3`, and its ``cfc:`` superclasses come from the Core graph rather
    than from local stubs.
    """
    load_shared_ontologies(db)
    db.import_statements(
        _read_demo_ontology("transferunit.ttl"), content_type="application/x-turtle"
    )


def create_resource(db, resource_iri: IRI, resource_class: IRI) -> None:
    """Instantiate a resource individual of the given class."""
    db.triple_add((resource_iri, RDF.type, resource_class))


def seed_scenario1(db) -> None:
    """Full scenario 1 seed: clear, load ontologies, and create the hello + planner resources."""
    clear_repository(db)
    load_scenario1_ontologies(db)
    create_resource(db, HELLO_RESOURCE, HELLO_RESOURCE_CLASS)
    create_resource(db, PLANNER_RESOURCE, PLANNER_RESOURCE_CLASS)


def seed_scenario3(db, ogm) -> None:
    """Full scenario 3 seed: clear, load the shared modules + TransferUnit classes, and
    create one TransferUnit with two conveyor belts and two light barriers **through the
    OGM**.

    Instances are created rather than authored as Turtle, so the seed exercises the same
    validated write path a running middleware uses (root ADR 0008) and the ontology file
    stays classes-only.

    No ``inf:hasValue`` literals: scenario 3 is a locator (ADR 0024). The graph records
    where each value lives; the live value exists only in the datamodel and over REST.
    """
    clear_repository(db)
    load_scenario3_ontologies(db)

    for belt, position in (
        (CONVEYOR_BELT_LEFT, "left"),
        (CONVEYOR_BELT_RIGHT, "right"),
    ):
        ogm.create(
            class_iri=CONVEYOR_BELT_CLASS,
            instance_iri=belt,
            class_scope=ClassScope.from_property_chains([[TU_HAS_CONVEYOR_SPEED]]),
            data={TU_HAS_CONVEYOR_SPEED: [{TU_HAS_UNIT: ["m/s"]}]},
        )
        _attach_connection_metadata(
            db,
            resource_iri=belt,
            parameter_property=TU_HAS_CONVEYOR_SPEED,
            access_mode="readwrite",
            topic=f"TransferUnit1/ConveyorBelt/{position}/speed",
            set_topic=f"TransferUnit1/ConveyorBelt/{position}/speed_set",
        )

    for barrier, position in (
        (LIGHT_BARRIER_FRONT, "front"),
        (LIGHT_BARRIER_BACK, "back"),
    ):
        ogm.create(
            class_iri=LIGHT_BARRIER_CLASS,
            instance_iri=barrier,
            class_scope=ClassScope.from_property_chains([[TU_IS_OCCUPIED]]),
            data={TU_IS_OCCUPIED: [{}]},
        )
        _attach_connection_metadata(
            db,
            resource_iri=barrier,
            parameter_property=TU_IS_OCCUPIED,
            access_mode="read",
            topic=f"TransferUnit1/LightBarrier/{position}/occupied",
        )

    ogm.create(
        class_iri=TRANSFER_UNIT_CLASS,
        instance_iri=TRANSFER_UNIT_1,
        class_scope=ClassScope.from_property_chains(
            [[TU_HAS_CONVEYOR_BELT], [TU_HAS_LIGHT_BARRIER]]
        ),
        data={
            TU_HAS_CONVEYOR_BELT: [
                {"id": CONVEYOR_BELT_LEFT},
                {"id": CONVEYOR_BELT_RIGHT},
            ],
            TU_HAS_LIGHT_BARRIER: [
                {"id": LIGHT_BARRIER_FRONT},
                {"id": LIGHT_BARRIER_BACK},
            ],
        },
    )


def _attach_connection_metadata(
    db,
    *,
    resource_iri: IRI,
    parameter_property: IRI,
    access_mode: str,
    topic: str,
    set_topic: Optional[str] = None,
) -> None:
    """Attach the MQTT connection metadata to a parameter node the OGM just created.

    **A documented stand-in, not the intended flow.** In production the middleware writes
    this metadata itself when the resource is first set up (ADR 0015 row 3; issue #54) —
    that is the moment the interface metadata is joined to the domain parameter.

    It cannot go through the OGM today: the write path serializes only what the range
    restriction declares, so ``ogm.create`` silently drops the topic, set topic and broker
    (issue #52; ``SAWeindel/kapps_ogm#7`` is the fix). Hence a targeted SPARQL INSERT, as
    an explicit exception to root ADR 0008 — to be deleted once #54 lands.

    The parameter node is anonymous and the OGM does not report the identifier it minted,
    so the node is reached by matching from the resource rather than by name — which is the
    same limitation ``SAWeindel/kapps_ogm#6`` removes.
    """
    inserts = [
        f'?parameter <{INF_ACCESS_MODE}> "{access_mode}" .',
        f'?parameter <{INF_HAS_MQTT_TOPIC}> "{topic}" .',
        f'?parameter <{INF_HAS_MQTT_BROKER_IP}> "{MQTT_BROKER_IP}" .',
    ]
    if set_topic is not None:
        inserts.append(f'?parameter <{INF_HAS_MQTT_SET_TOPIC}> "{set_topic}" .')

    db.query(
        f"INSERT {{ {' '.join(inserts)} }} "
        f"WHERE {{ <{resource_iri}> <{parameter_property}> ?parameter }}",
        update=True,
    )


def seed_scenario2(db) -> None:
    """Full scenario 2 (door) seed: clear, load ontologies, create the door + robot resources."""
    clear_repository(db)
    load_scenario2_ontologies(db)
    create_resource(db, DOOR_RESOURCE, DOOR_RESOURCE_CLASS)
    create_resource(db, MOBILE_ROBOT, MOBILE_ROBOT_RESOURCE_CLASS)


def _read_mes_ontology() -> str:
    """Return the packaged mes: ontology Turtle (handover-ability vocabulary)."""
    return (
        resources.files("kapps_semantic_middleware")
        .joinpath("ontology", "mes.ttl")
        .read_text(encoding="utf-8")
    )


def seed_handover(db, ogm) -> None:
    """Full handover seed: clear, load the mes: + handover ontologies, create two transfer
    modules and a box, give the destination the ability complementary to Pass (Retrieve), and
    make the source currently possess the box (Core reified possession, written via the OGM)."""
    clear_repository(db)
    db.import_statements(_read_mes_ontology(), content_type="application/x-turtle")
    db.import_statements(
        _read_demo_ontology("demo_handover.ttl"), content_type="application/x-turtle"
    )
    create_resource(db, HANDOVER_SOURCE, TRANSFER_MODULE_CLASS)
    create_resource(db, HANDOVER_DEST, TRANSFER_MODULE_CLASS)
    create_resource(db, HANDOVER_BOX, BOX_CLASS)
    # The destination carries the ability complementary to Pass (Retrieve).
    db.triple_add((HANDOVER_DEST, MES.hasHandoverAbility, MES.Retrieve))
    # The source currently possesses the box.
    create_possession(ogm, workpiece_iri=HANDOVER_BOX, possessor_iri=HANDOVER_SOURCE)


# Resource *class* IRIs (instances above are typed with these).
HELLO_RESOURCE_CLASS = IRI(f"{DEMO_NS}DemoResource")
PLANNER_RESOURCE_CLASS = IRI(f"{DEMO_NS}PlannerResource")
