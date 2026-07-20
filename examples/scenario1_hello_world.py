"""Scenario 1: hello-world workflow through the knowledge graph.

A debugger-friendly, plain-Python equivalent of ``scenario1_hello_world.ipynb``. It
connects to the dedicated GraphDB repository configured through ``GRAPHDB_*`` environment
variables, clears and seeds it, then drives the complete **operation-coordination**
lifecycle: registration, graph discovery, dispatch through the event trigger, pull-and-run,
provenance, and deregistration.

Run this file from a debugger or as a script. The numbered functions correspond to the
notebook's steps and provide convenient debugger breakpoints.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import uvicorn
from graph_db_interface import GraphDB, IRI
from rdflib.namespace import RDF

from handlers import hello_world
from kapps_ogm import OGM
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.registration import (
    mint_capability_iri,
    mint_workflow_iri,
)
from kapps_semantic_middleware.vocabulary import CFC, OperationStatus, SVC

import seed

HELLO_PORT = 8993
PLANNER_PORT = 8994
SERVER_START_TIMEOUT_SECONDS = 30
SERVER_STOP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Registration:
    """Identifiers created deterministically during hello-world registration."""

    service_iri: IRI
    capability_iri: IRI
    workflow_iri: IRI


def step_1_seed_clean_repository(db: GraphDB) -> None:
    """Clear the dedicated repository, load Scenario 1 ontology, and create resources."""
    print("\nStep 1 — Seed a Clean Repository")
    seed.seed_scenario1(db)

    hello_exists = db.triple_exists((seed.HELLO_RESOURCE, RDF.type, seed.HELLO_RESOURCE_CLASS))
    planner_exists = db.triple_exists(
        (seed.PLANNER_RESOURCE, RDF.type, seed.PLANNER_RESOURCE_CLASS)
    )
    print(f"Hello resource instantiated:   {hello_exists}")
    print(f"Planner resource instantiated: {planner_exists}")


def _start_server(middleware: SemanticMiddleware, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    """Start a middleware server and wait until its startup registration completes."""
    config = uvicorn.Config(middleware.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    started_at = time.time()
    while not server.started and time.time() - started_at < SERVER_START_TIMEOUT_SECONDS:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server did not start in time")
    return server, thread


def step_2_start_hello_world_middleware(db: GraphDB) -> tuple[SemanticMiddleware, uvicorn.Server, threading.Thread]:
    """Register the hello-world workflow and start its HTTP server."""
    print("\nStep 2 — Start the Hello-World Middleware")
    middleware = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.HELLO_RESOURCE,
        service_class=seed.HELLO_SERVICE_CLASS,
        ogm=OGM(db=db),
        host="127.0.0.1",
        port=HELLO_PORT,
    )
    middleware.workflow(
        capability_class=seed.HELLO_CAPABILITY_CLASS,
        workflow_class=seed.HELLO_WORKFLOW_CLASS,
    )(hello_world)

    server, thread = _start_server(middleware, HELLO_PORT)
    print(f"Hello-world middleware started on port {HELLO_PORT} (registered on startup)")
    print(f"Swagger UI:  http://127.0.0.1:{HELLO_PORT}/docs")
    print("Registered routes:", [route.path for route in middleware.app.routes if "workflows" in route.path])
    return middleware, server, thread


def step_3_inspect_registration(db: GraphDB) -> Registration:
    """Verify the Service/Capability/Workflow structure and reachability triples."""
    print("\nStep 3 — Inspect What Registration Wrote")
    service_iri = seed.HELLO_RESOURCE + "_service"
    capability_iri = mint_capability_iri(seed.HELLO_RESOURCE, "hello_world")
    workflow_iri = mint_workflow_iri(service_iri, "hello_world")

    print(f"Service IRI:    {service_iri}")
    print(f"Capability IRI: {capability_iri}")
    print(f"Workflow IRI:   {workflow_iri}\n")

    assert db.triple_exists((service_iri, RDF.type, seed.HELLO_SERVICE_CLASS))
    assert db.triple_exists((service_iri, SVC.isServiceOf, seed.HELLO_RESOURCE))
    assert db.triple_exists((capability_iri, SVC.realizedByWorkflow, workflow_iri))
    assert db.triple_exists((workflow_iri, SVC.isWorkflowOf, service_iri))
    print("Structural triples present (isServiceOf, realizedByWorkflow, isWorkflowOf).")
    print("Note: only the instance-owned direction of each inverse is materialized (ADR 0008).")

    address_triples = list(db.triples_get(sub=service_iri, pred=SVC.address))
    endpoint_triples = list(db.triples_get(sub=workflow_iri, pred=SVC.endpoint))
    print(f"Service address advertised:   {address_triples[0][2] if address_triples else 'NONE'}")
    print(f"Workflow endpoint advertised: {endpoint_triples[0][2] if endpoint_triples else 'NONE'}")
    return Registration(service_iri, capability_iri, workflow_iri)


def step_4_dispatch_and_run(
    db: GraphDB, hello_mw: SemanticMiddleware, registration: Registration
) -> IRI:
    """Dispatch an operation through the event trigger, then pull-and-run it.

    A second middleware (a planner) dispatches an operation for the hello capability: it
    creates the Operation ``queued`` in the graph and rings the hello resource's event
    trigger over REST — resolving the peer purely through the graph. The hello resource
    then pulls the queued operation and runs the work (ADR 0009/0010).
    """
    print("\nStep 4 — Dispatch through the Event Trigger, then Pull-and-Run")
    planner = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.PLANNER_RESOURCE,
        service_class=seed.PLANNER_SERVICE_CLASS,
        ogm=OGM(db=db),
        host="127.0.0.1",
        port=PLANNER_PORT,
    )
    with planner.request(
        capability_class=seed.HELLO_CAPABILITY_CLASS,
        operation_class=str(CFC.Operation),
    ) as op:
        pass  # helloworld takes no arguments to populate
    op_iri = op.iri
    print(f"Planner dispatched operation: {op_iri}")
    print(f"  addressed via capability {registration.capability_iri}; queued on the hello resource")

    with hello_mw.claim_next() as claimed:
        claimed.result = hello_world()
    print(f"Hello resource pulled and ran the operation -> result: {claimed.result!r}")
    return op_iri


def step_5_inspect_decision_provenance(db: GraphDB, operation_iri: IRI) -> None:
    """Display the terminal status + execution provenance written to the Operation."""
    print("\nStep 5 — The Decision is Now Traceable in the Graph (R12)")
    status = list(db.triples_get(sub=operation_iri, pred=SVC.operationStatus))
    executed_by = list(db.triples_get(sub=operation_iri, pred=SVC.executedByWorkflow))
    timestamp = list(db.triples_get(sub=operation_iri, pred=SVC.executionTimestamp))
    result = list(db.triples_get(sub=operation_iri, pred=SVC.executionResult))

    print(f"Terminal state + provenance recorded on {operation_iri}:")
    print(f"  operationStatus:    {status[0][2] if status else 'NONE'}")
    print(f"  executedByWorkflow: {executed_by[0][2] if executed_by else 'NONE'}")
    print(f"  executionTimestamp: {timestamp[0][2] if timestamp else 'NONE'}")
    print(f"  executionResult:    {result[0][2] if result else 'NONE'}")
    assert status and str(status[0][2]) == OperationStatus.DONE


def step_6_shutdown_and_verify(
    db: GraphDB, registration: Registration, server: uvicorn.Server, thread: threading.Thread
) -> None:
    """Stop the server and verify reachability is removed while individuals remain."""
    print("\nStep 6 — Shutdown and Deregistration")
    server.should_exit = True
    thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
    time.sleep(0.5)

    address_after = list(db.triples_get(sub=registration.service_iri, pred=SVC.address))
    endpoint_after = list(db.triples_get(sub=registration.workflow_iri, pred=SVC.endpoint))
    print("After shutdown:")
    print(f"  Service address removed:   {len(address_after) == 0}")
    print(f"  Workflow endpoint removed: {len(endpoint_after) == 0}")
    print(
        "  Workflow individual preserved (rdf:type): "
        f"{db.triple_exists((registration.workflow_iri, RDF.type, seed.HELLO_WORKFLOW_CLASS))}"
    )


def main() -> None:
    """Run the complete Scenario 1 lifecycle."""
    db = GraphDB.from_env()
    print(f"Connected to GraphDB repository: {os.getenv('GRAPHDB_REPOSITORY')}")

    step_1_seed_clean_repository(db)
    hello_mw, server, thread = step_2_start_hello_world_middleware(db)
    registration: Registration | None = None
    try:
        registration = step_3_inspect_registration(db)
        operation_iri = step_4_dispatch_and_run(db, hello_mw, registration)
        step_5_inspect_decision_provenance(db, operation_iri)
    finally:
        if registration is not None:
            step_6_shutdown_and_verify(db, registration, server, thread)
        else:
            server.should_exit = True
            thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)


if __name__ == "__main__":
    main()
