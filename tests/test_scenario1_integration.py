"""Scenario 1 end-to-end integration test against a live GraphDB.

Drives the public SemanticMiddleware API (the one test seam): a hello-world
middleware registers a workflow on startup, a second middleware resolves an
Operation to that workflow and invokes it over real HTTP, and the graph is
asserted at each step. Skipped when GRAPHDB_* env vars are absent (see conftest).
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from rdflib.namespace import RDF

from kapps_ogm import OGM
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.registration import (
    mint_capability_iri,
    mint_workflow_iri,
)
from kapps_semantic_middleware.vocabulary import CFC, SVC

requires_graphdb = pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in ("GRAPHDB_URL", "GRAPHDB_USERNAME", "GRAPHDB_PASSWORD", "GRAPHDB_REPOSITORY")
    ),
    reason="GRAPHDB_* environment variables not set; skipping live-GraphDB integration test",
)

# examples/ is not a package; add it to the path to reuse the scenario seed helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import seed  # noqa: E402

HELLO_PORT = 8993


def hello_world() -> str:
    """The most basic workflow: return a greeting."""
    return "hello world"


def _start_server(mw: SemanticMiddleware, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(mw.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    t0 = time.time()
    while not server.started and time.time() - t0 < 30:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("server did not start in time")
    return server, thread


@requires_graphdb
def test_scenario1_hello_world_end_to_end(graphdb):
    db = graphdb
    seed.seed_scenario1(db)

    service_iri = seed.HELLO_RESOURCE + "_service"
    cap_instance = mint_capability_iri(seed.HELLO_RESOURCE, "hello_world")
    wf_instance = mint_workflow_iri(service_iri, "hello_world")

    mw1 = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.HELLO_RESOURCE,
        service_class=seed.HELLO_SERVICE_CLASS,
        ogm=OGM(db=graphdb.__class__.from_env()),
        host="127.0.0.1",
        port=HELLO_PORT,
    )
    mw1.workflow(
        capability_class=seed.HELLO_CAPABILITY_CLASS,
        workflow_class=seed.HELLO_WORKFLOW_CLASS,
    )(hello_world)

    server, thread = _start_server(mw1, HELLO_PORT)
    try:
        # Registration wrote the full Service/Capability/Workflow structure + reachability.
        assert db.triple_exists((seed.HELLO_RESOURCE, SVC.hasService, service_iri))
        assert db.triple_exists((service_iri, RDF.type, seed.HELLO_SERVICE_CLASS))
        assert db.triple_exists((seed.HELLO_RESOURCE, CFC.hasCapability, cap_instance))
        assert db.triple_exists((cap_instance, SVC.realizedByWorkflow, wf_instance))
        assert db.triple_exists((service_iri, SVC.hasWorkflow, wf_instance))
        assert db.triples_get(sub=service_iri, pred=SVC.address)
        assert db.triples_get(sub=wf_instance, pred=SVC.endpoint)

        # An Operation implementing the (now-registered) capability instance.
        seed.create_operation(db, seed.HELLO_OPERATION, cap_instance)

        # A second middleware resolves + invokes the operation over HTTP.
        mw2 = SemanticMiddleware(
            mode="resource",
            resource_iri=seed.PLANNER_RESOURCE,
            service_class=seed.PLANNER_SERVICE_CLASS,
            ogm=OGM(db=graphdb.__class__.from_env()),
            host="127.0.0.1",
            port=8994,
        )
        result = asyncio.run(mw2.execute(seed.HELLO_OPERATION))
        assert result["success"] is True
        assert result["result"] == "hello world"
        assert result["workflow"] == str(wf_instance)

        # R12 provenance was written back onto the operation.
        assert db.triple_exists((seed.HELLO_OPERATION, SVC.executedByWorkflow, wf_instance))
        assert db.triples_get(sub=seed.HELLO_OPERATION, pred=SVC.executionSuccess)
        assert db.triples_get(sub=seed.HELLO_OPERATION, pred=SVC.executionTimestamp)
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        time.sleep(0.5)

    # Deregistration on shutdown removed reachability but preserved the individuals.
    assert not db.triples_get(sub=service_iri, pred=SVC.address)
    assert not db.triples_get(sub=wf_instance, pred=SVC.endpoint)
    assert db.triple_exists((wf_instance, RDF.type, seed.HELLO_WORKFLOW_CLASS))


@requires_graphdb
def test_missing_ground_truth_class_fails_fast(graphdb):
    """A workflow referencing a non-existent class is rejected at registration (ADR 0003)."""
    from kapps_semantic_middleware.registration import (
        OntologyGroundTruthError,
        register_workflow,
    )

    seed.seed_scenario1(graphdb)
    with pytest.raises(OntologyGroundTruthError):
        register_workflow(
            graphdb,
            resource_iri=seed.HELLO_RESOURCE,
            service_iri=seed.HELLO_RESOURCE + "_service",
            workflow_iri=seed.HELLO_RESOURCE + "_service_workflow_ghost",
            workflow_class="https://example.org/kapps-demo#NonexistentWorkflow",
            capability_iri=mint_capability_iri(seed.HELLO_RESOURCE, "ghost"),
            capability_class=seed.HELLO_CAPABILITY_CLASS,
            endpoint="http://127.0.0.1:9/workflows/ghost/execute",
        )
