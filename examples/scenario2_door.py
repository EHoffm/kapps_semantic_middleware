"""Scenario 2: a door and a mobile robot — direct workflow/state invocation.

A debugger-friendly, plain-Python equivalent of ``scenario2_door.ipynb``. It demonstrates
the *direct* interaction pattern (as opposed to scenario 1's operation coordination): a
door resource exposes open/close workflows and a live status StateProperty, with **no
operation queue**; a minimal mobile robot discovers the door purely through the knowledge
graph (a SPARQL query), reads its live status over the StateProperty GET endpoint, and —
finding it closed — invokes the door's open workflow directly at the endpoint it found in
the graph. Not operation based.

Run from a debugger or as a script. The numbered functions are convenient breakpoints.
"""

from __future__ import annotations

import os
import threading
import time

import httpx
import uvicorn
from graph_db_interface import GraphDB
from rdflib.namespace import RDF

from handlers import door_close, door_open, door_status, reset_door
from kapps_ogm import OGM
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.registration import (
    mint_capability_iri,
    mint_state_property_iri,
    mint_workflow_iri,
)
from kapps_semantic_middleware.vocabulary import SVC

import seed

DOOR_PORT = 8997
ROBOT_PORT = 8998
SERVER_START_TIMEOUT_SECONDS = 30
SERVER_STOP_TIMEOUT_SECONDS = 20


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


def step_1_seed_clean_repository(db: GraphDB) -> None:
    """Clear the repository, load the Scenario 2 ontology, and create the door + robot."""
    print("\nStep 1 — Seed a Clean Repository")
    reset_door()
    seed.seed_scenario2(db)
    door_exists = db.triple_exists((seed.DOOR_RESOURCE, RDF.type, seed.DOOR_RESOURCE_CLASS))
    robot_exists = db.triple_exists(
        (seed.MOBILE_ROBOT, RDF.type, seed.MOBILE_ROBOT_RESOURCE_CLASS)
    )
    print(f"Door resource instantiated:  {door_exists}")
    print(f"Robot resource instantiated: {robot_exists}")


def step_2_start_door_middleware(db: GraphDB) -> tuple[SemanticMiddleware, uvicorn.Server, threading.Thread]:
    """Register the door's two workflows + live status StateProperty, and start its server."""
    print("\nStep 2 — Start the Door Middleware")
    door = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.DOOR_RESOURCE,
        service_class=seed.DOOR_SERVICE_CLASS,
        ogm=OGM(db=db),
        host="127.0.0.1",
        port=DOOR_PORT,
    )
    door.workflow(
        capability_class=seed.DOOR_OPEN_CAPABILITY_CLASS,
        workflow_class=seed.DOOR_OPEN_WORKFLOW_CLASS,
    )(door_open)
    door.workflow(
        capability_class=seed.DOOR_CLOSE_CAPABILITY_CLASS,
        workflow_class=seed.DOOR_CLOSE_WORKFLOW_CLASS,
    )(door_close)
    door.state(
        capability_class=seed.DOOR_STATUS_CAPABILITY_CLASS,
        state_property_class=seed.DOOR_STATUS_STATE_CLASS,
    )(door_status)
    server, thread = _start_server(door, DOOR_PORT)
    print(f"Door middleware started on port {DOOR_PORT} (no operation queue — direct invocation)")
    print("Routes:", [r.path for r in door.app.routes if "workflows" in r.path or "state" in r.path])
    return door, server, thread


def step_3_inspect_registration(db: GraphDB) -> str:
    """Verify the door's workflows, state property, and reachable endpoints are in the graph."""
    print("\nStep 3 — Inspect What Registration Wrote")
    service_iri = seed.DOOR_RESOURCE + "_service"
    open_wf = mint_workflow_iri(service_iri, "door_open")
    status_sp = mint_state_property_iri(service_iri, "door_status")
    status_cap = mint_capability_iri(seed.DOOR_RESOURCE, "door_status")

    assert db.triple_exists((open_wf, SVC.isWorkflowOf, service_iri))
    assert db.triple_exists((status_sp, SVC.isStatePropertyOf, service_iri))
    assert db.triple_exists((status_cap, SVC.providedByStateProperty, status_sp))
    open_url = list(db.triples_get(sub=open_wf, pred=SVC.endpoint))
    status_url = list(db.triples_get(sub=status_sp, pred=SVC.endpoint))
    print(f"Open workflow endpoint:  {open_url[0][2] if open_url else 'NONE'}")
    print(f"Status state endpoint:   {status_url[0][2] if status_url else 'NONE'}")
    return service_iri


def _discover_door_endpoints(ogm, door_resource_iri) -> tuple[str, str]:
    """Discover the door's live-state GET endpoint and open-workflow execute URL via SPARQL."""
    sparql = f"""
    SELECT ?status_url ?open_url WHERE {{
        ?svc <{SVC.isServiceOf}> <{door_resource_iri}> .
        ?sp <{SVC.isStatePropertyOf}> ?svc .
        ?sp a <{seed.DOOR_STATUS_STATE_CLASS}> .
        ?sp <{SVC.endpoint}> ?status_url .
        ?wf <{SVC.isWorkflowOf}> ?svc .
        ?wf a <{seed.DOOR_OPEN_WORKFLOW_CLASS}> .
        ?wf <{SVC.endpoint}> ?open_url .
    }}
    """
    result = ogm.db.query(sparql, convert_bindings=True)
    bindings = result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
    assert bindings, "robot could not discover the door's endpoints in the knowledge graph"
    b = bindings[0]
    return str(b["status_url"]), str(b["open_url"])


def step_4_robot_passes_through_door(robot_ogm, door_resource_iri) -> None:
    """The mobile robot's scripted behaviour: discover the door, ensure it is open, pass it.

    Deterministic, one step after another; the only forks are "is the door open?" and, if
    not, "open it". Discovery is via SPARQL; the live state and the workflow invocation are
    direct REST calls to the endpoints found in the graph.
    """
    print("\nStep 4 — The Mobile Robot Discovers and Passes the Door")
    status_url, open_url = _discover_door_endpoints(robot_ogm, door_resource_iri)
    print(f"Robot discovered (via SPARQL): status={status_url}")
    print(f"                               open  ={open_url}")

    def ensure_open(phase: str) -> None:
        state = httpx.get(status_url).json()
        print(f"  {phase}: door is {state}")
        if state == "closed":
            httpx.post(open_url)  # invoke the open workflow directly at its execute URL
            print(f"  {phase}: door was closed -> invoked the open workflow directly")
            state = httpx.get(status_url).json()
            print(f"  {phase}: door is now {state}")
        assert state == "opened", f"door failed to open ({phase})"

    ensure_open("approach")
    print("  drove through the door")
    # (Story: drop the load behind the door, then drive back. The door auto-closes after
    # 30 s, but the drop-off took less, so on return it is still open.)
    ensure_open("return")
    print("  drove back through the door")


def step_5_verify_state_not_persisted(db: GraphDB, service_iri: str) -> None:
    """Confirm the live status value is never written to the graph."""
    print("\nStep 5 — The Live Status is Never Persisted")
    status_sp = mint_state_property_iri(service_iri, "door_status")
    for _, _, obj in db.triples_get(sub=status_sp):
        assert str(obj) not in ("opened", "closed"), "state value must not be persisted"
    print("Confirmed: no 'opened'/'closed' literal is written onto the state property.")


def step_6_shutdown(db: GraphDB, service_iri: str, server: uvicorn.Server, thread: threading.Thread) -> None:
    """Stop the door server and verify reachability is removed while the individual remains."""
    print("\nStep 6 — Shutdown and Deregistration")
    server.should_exit = True
    thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
    time.sleep(0.5)
    status_sp = mint_state_property_iri(service_iri, "door_status")
    endpoint_gone = len(list(db.triples_get(sub=status_sp, pred=SVC.endpoint))) == 0
    preserved = db.triple_exists((status_sp, RDF.type, seed.DOOR_STATUS_STATE_CLASS))
    print(f"  State property endpoint removed:    {endpoint_gone}")
    print(f"  State property individual preserved: {preserved}")


def main() -> None:
    """Run the complete Scenario 2 lifecycle."""
    db = GraphDB.from_env()
    print(f"Connected to GraphDB repository: {os.getenv('GRAPHDB_REPOSITORY')}")

    step_1_seed_clean_repository(db)
    _door_mw, server, thread = step_2_start_door_middleware(db)
    service_iri: str | None = None
    try:
        service_iri = step_3_inspect_registration(db)
        # The mobile robot: a minimal second middleware. Its scripted logic discovers and
        # drives the door through the graph + REST, using its own OGM for the SPARQL query.
        robot = SemanticMiddleware(
            mode="resource",
            resource_iri=seed.MOBILE_ROBOT,
            service_class=seed.MOBILE_ROBOT_SERVICE_CLASS,
            ogm=OGM(db=GraphDB.from_env()),
            host="127.0.0.1",
            port=ROBOT_PORT,
        )
        step_4_robot_passes_through_door(robot.ogm, seed.DOOR_RESOURCE)
        step_5_verify_state_not_persisted(db, service_iri)
    finally:
        reset_door()
        if service_iri is not None:
            step_6_shutdown(db, service_iri, server, thread)
        else:
            server.should_exit = True
            thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)


if __name__ == "__main__":
    main()
