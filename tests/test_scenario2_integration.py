"""Scenario 2 end-to-end integration test against a live GraphDB.

A decentrally-controlled door exposes two workflows (open, close) and one live
StateProperty (status). Driving the public API: registration writes the full
structure, execute() opens/closes the door over HTTP, and the status is served
live over GET while never being persisted to the graph. Skipped when GRAPHDB_*
env vars are absent.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from rdflib.namespace import RDF

from kapps_ogm import OGM
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.registration import (
    mint_capability_iri,
    mint_state_property_iri,
    mint_workflow_iri,
)
from kapps_semantic_middleware.vocabulary import SVC

requires_graphdb = pytest.mark.skipif(
    not all(
        os.getenv(n)
        for n in ("GRAPHDB_URL", "GRAPHDB_USERNAME", "GRAPHDB_PASSWORD", "GRAPHDB_REPOSITORY")
    ),
    reason="GRAPHDB_* environment variables not set; skipping live-GraphDB integration test",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import seed  # noqa: E402

DOOR_PORT = 8997

# In-memory door state — mutated by the workflows, read by the state getter.
# It is deliberately NOT in the knowledge graph.
_door = {"status": "closed"}


def door_open() -> str:
    _door["status"] = "opened"
    return "opened"


def door_close() -> str:
    _door["status"] = "closed"
    return "closed"


def door_status() -> str:
    return _door["status"]


def _start_server(mw, port):
    config = uvicorn.Config(mw.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    t0 = time.time()
    while not server.started and time.time() - t0 < 30:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server did not start")
    return server, thread


@requires_graphdb
def test_scenario2_door_workflows_and_live_state(graphdb):
    db = graphdb
    _door["status"] = "closed"
    seed.seed_scenario2(db)

    service_iri = seed.DOOR_RESOURCE + "_service"
    open_wf = mint_workflow_iri(service_iri, "door_open")
    close_wf = mint_workflow_iri(service_iri, "door_close")
    status_sp = mint_state_property_iri(service_iri, "door_status")

    mw = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.DOOR_RESOURCE,
        service_class=seed.DOOR_SERVICE_CLASS,
        ogm=OGM(db=graphdb.__class__.from_env()),
        host="127.0.0.1",
        port=DOOR_PORT,
    )
    mw.workflow(
        capability_class=seed.DOOR_OPEN_CAPABILITY_CLASS,
        workflow_class=seed.DOOR_OPEN_WORKFLOW_CLASS,
    )(door_open)
    mw.workflow(
        capability_class=seed.DOOR_CLOSE_CAPABILITY_CLASS,
        workflow_class=seed.DOOR_CLOSE_WORKFLOW_CLASS,
    )(door_close)
    mw.state(
        capability_class=seed.DOOR_STATUS_CAPABILITY_CLASS,
        state_property_class=seed.DOOR_STATUS_STATE_CLASS,
    )(door_status)

    server, thread = _start_server(mw, DOOR_PORT)
    try:
        # Registration: both workflows and the state property are in the graph.
        # Links materialized on the instance-owned (inverse) side (ADR 0006).
        assert db.triple_exists((open_wf, SVC.isWorkflowOf, service_iri))
        assert db.triple_exists((close_wf, SVC.isWorkflowOf, service_iri))
        assert db.triple_exists((status_sp, SVC.isStatePropertyOf, service_iri))
        assert db.triple_exists((status_sp, RDF.type, seed.DOOR_STATUS_STATE_CLASS))
        status_cap = mint_capability_iri(seed.DOOR_RESOURCE, "door_status")
        assert db.triple_exists((status_cap, SVC.providedByStateProperty, status_sp))
        assert db.triples_get(sub=status_sp, pred=SVC.endpoint)

        base = f"http://127.0.0.1:{DOOR_PORT}"

        # Live state: served over GET, initially closed.
        r = httpx.get(f"{base}/state/door_status")
        assert r.status_code == 200 and r.json() == "closed", r.text

        # Open the door via the resolved operation, then the live state reflects it.
        seed.create_operation(
            db, seed.DOOR_OPEN_OPERATION, mint_capability_iri(seed.DOOR_RESOURCE, "door_open")
        )
        res_open = asyncio.run(mw.execute(seed.DOOR_OPEN_OPERATION))
        assert res_open["success"] and res_open["result"] == "opened", res_open
        assert httpx.get(f"{base}/state/door_status").json() == "opened"

        # Close it again; the live GET tracks the in-memory change.
        seed.create_operation(
            db, seed.DOOR_CLOSE_OPERATION, mint_capability_iri(seed.DOOR_RESOURCE, "door_close")
        )
        res_close = asyncio.run(mw.execute(seed.DOOR_CLOSE_OPERATION))
        assert res_close["success"] and res_close["result"] == "closed", res_close
        assert httpx.get(f"{base}/state/door_status").json() == "closed"

        # The live value is NEVER written to the graph: the state property carries only
        # structural triples + endpoint, and no "opened"/"closed" literal appears anywhere.
        sp_predicates = {
            str(p) for _, p, _ in db.triples_get(sub=status_sp)
        }
        assert str(SVC.endpoint) in sp_predicates
        for _, _, obj in db.triples_get(sub=status_sp):
            assert str(obj) not in ("opened", "closed"), "state value must not be persisted"
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        time.sleep(0.5)

    # Deregistration removed the state property endpoint too, but kept the individual.
    assert not db.triples_get(sub=status_sp, pred=SVC.endpoint)
    assert db.triple_exists((status_sp, RDF.type, seed.DOOR_STATUS_STATE_CLASS))
