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

from graph_db_interface import IRI
from rdflib.namespace import RDF

from kapps_semantic_middleware.vocabulary import CFC

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
HELLO_OPERATION = IRI(f"{DEMO_NS}helloWorldOperation_1")

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
DOOR_OPEN_OPERATION = IRI(f"{DEMO_NS}doorOpenOperation_1")
DOOR_CLOSE_OPERATION = IRI(f"{DEMO_NS}doorCloseOperation_1")

# Mobile robot (scenario 2 consumer): discovers and drives the door through the graph.
MOBILE_ROBOT_RESOURCE_CLASS = IRI(f"{DEMO_NS}MobileRobotResource")
MOBILE_ROBOT_SERVICE_CLASS = IRI(f"{DEMO_NS}MobileRobotControllerService")
MOBILE_ROBOT = IRI(f"{DEMO_NS}mobile_robot_007")


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


def load_scenario1_ontologies(db) -> None:
    """Load the ``svc:`` module and ONLY the scenario 1 demo classes into the repo."""
    db.import_statements(_read_service_ontology(), content_type="application/x-turtle")
    db.import_statements(
        _read_demo_ontology("demo_scenario1.ttl"), content_type="application/x-turtle"
    )


def load_scenario2_ontologies(db) -> None:
    """Load the ``svc:`` module and ONLY the scenario 2 (door) demo classes into the repo."""
    db.import_statements(_read_service_ontology(), content_type="application/x-turtle")
    db.import_statements(
        _read_demo_ontology("demo_scenario2.ttl"), content_type="application/x-turtle"
    )


def create_resource(db, resource_iri: IRI, resource_class: IRI) -> None:
    """Instantiate a resource individual of the given class."""
    db.triple_add((resource_iri, RDF.type, resource_class))


def create_operation(db, operation_iri: IRI, capability_iri: IRI) -> None:
    """Create an Operation instance targeting a Capability instance.

    The Operation implements a Capability (``cfc:implementsCapability``); at
    execution time the middleware resolves that Capability to the Workflow that
    realizes it. ``capability_iri`` is the capability *instance* the middleware
    minted when it registered the workflow (deterministic, so the scenario can
    reference it up front).
    """
    db.triple_add((operation_iri, RDF.type, CFC.Operation))
    db.triple_add((operation_iri, CFC.implementsCapability, capability_iri))


def seed_scenario1(db) -> None:
    """Full scenario 1 seed: clear, load ontologies, create the two resources.

    The Operation is created separately (after the hello-world middleware has
    registered its capability instance) via :func:`create_operation`.
    """
    clear_repository(db)
    load_scenario1_ontologies(db)
    create_resource(db, HELLO_RESOURCE, HELLO_RESOURCE_CLASS)
    create_resource(db, PLANNER_RESOURCE, PLANNER_RESOURCE_CLASS)


def seed_scenario2(db) -> None:
    """Full scenario 2 (door) seed: clear, load ontologies, create the door resource.

    The open/close Operations are created separately (after the door middleware
    has registered its capability instances) via :func:`create_operation`. The
    demo ontology is shared with scenario 1, so the same loader applies.
    """
    clear_repository(db)
    load_scenario2_ontologies(db)
    create_resource(db, DOOR_RESOURCE, DOOR_RESOURCE_CLASS)
    create_resource(db, MOBILE_ROBOT, MOBILE_ROBOT_RESOURCE_CLASS)


# Resource *class* IRIs (instances above are typed with these).
HELLO_RESOURCE_CLASS = IRI(f"{DEMO_NS}DemoResource")
PLANNER_RESOURCE_CLASS = IRI(f"{DEMO_NS}PlannerResource")
