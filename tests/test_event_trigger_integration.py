"""Event-trigger coordination end-to-end integration test (#13) against a live GraphDB.

Proves the decentralized event trigger over REST (ADR 0009): resource A *dispatches* an
Operation to resource B by creating it in the graph (status ``queued``) and triggering B's
event-trigger endpoint over HTTP; B enqueues it and leaves it ``queued``. Also covers the
atomic revert (ADR 0010): a dispatch whose trigger cannot be delivered removes the created
Operation. Skipped when GRAPHDB_* env vars are absent (see conftest).
"""

from __future__ import annotations

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
    register_service,
    register_workflow,
)
from kapps_semantic_middleware.vocabulary import CFC, OperationStatus, SVC

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

B_PORT = 8995


def hello_world() -> str:
    """B's domain workflow — the same trivial greeting as scenario 1."""
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
def test_event_trigger_dispatch_enqueues_over_rest(graphdb):
    """A dispatches -> B's event trigger over REST -> B enqueues -> Operation queued in the graph."""
    db = graphdb
    seed.seed_scenario1(db)

    b_service = seed.HELLO_RESOURCE + "_service"
    cap_instance = mint_capability_iri(seed.HELLO_RESOURCE, "hello_world")

    # B: the hello resource, exposing helloworld + the built-in event trigger over REST.
    mw_b = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.HELLO_RESOURCE,
        service_class=seed.HELLO_SERVICE_CLASS,
        ogm=OGM(db=graphdb.__class__.from_env()),
        host="127.0.0.1",
        port=B_PORT,
    )
    mw_b.workflow(
        capability_class=seed.HELLO_CAPABILITY_CLASS,
        workflow_class=seed.HELLO_WORKFLOW_CLASS,
    )(hello_world)

    server, thread = _start_server(mw_b, B_PORT)
    try:
        assert db.triples_get(sub=b_service, pred=SVC.address)

        # A: the planner, dispatching an Operation for B's capability (no hardcoded peer).
        mw_a = SemanticMiddleware(
            mode="resource",
            resource_iri=seed.PLANNER_RESOURCE,
            service_class=seed.PLANNER_SERVICE_CLASS,
            ogm=OGM(db=graphdb.__class__.from_env()),
            host="127.0.0.1",
            port=8996,
        )

        with mw_a.request(
            capability_class=seed.HELLO_CAPABILITY_CLASS,
            operation_class=str(CFC.Operation),
        ) as op:
            pass  # helloworld takes no arguments; nothing to populate on the draft
        op_iri = op.iri

        # The dispatch created the Operation queued in the graph, addressed via its Capability.
        assert db.triple_exists((op_iri, RDF.type, CFC.Operation))
        assert db.triple_exists((op_iri, CFC.implementsCapability, cap_instance))
        status = list(db.triples_get(sub=op_iri, pred=SVC.operationStatus))
        assert status and str(status[0][2]) == OperationStatus.QUEUED

        # The event trigger reached B over REST and B enqueued it (receiver queue state).
        assert op_iri in mw_b._operation_queue
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        time.sleep(0.5)


@requires_graphdb
def test_event_trigger_revert_on_undeliverable(graphdb):
    """A dispatch whose event trigger cannot be delivered reverts the created Operation (ADR 0010)."""
    db = graphdb
    seed.seed_scenario1(db)

    # Seed a reachable-looking receiver whose address points at a dead port (no server is
    # started), so resolution succeeds but the event-trigger POST fails to connect.
    dead_service = seed.HELLO_RESOURCE + "_service"
    cap_instance = mint_capability_iri(seed.HELLO_RESOURCE, "hello_world")
    ogm = OGM(db=db)
    register_service(
        ogm,
        resource_iri=seed.HELLO_RESOURCE,
        service_iri=dead_service,
        service_class=seed.HELLO_SERVICE_CLASS,
        address="http://127.0.0.1:9",  # nothing listens on port 9
    )
    register_workflow(
        ogm,
        resource_iri=seed.HELLO_RESOURCE,
        service_iri=dead_service,
        workflow_iri=seed.HELLO_RESOURCE + "_service_workflow_hello_world",
        workflow_class=seed.HELLO_WORKFLOW_CLASS,
        capability_iri=cap_instance,
        capability_class=seed.HELLO_CAPABILITY_CLASS,
        endpoint="http://127.0.0.1:9/workflows/hello_world/execute",
    )

    mw_a = SemanticMiddleware(
        mode="resource",
        resource_iri=seed.PLANNER_RESOURCE,
        service_class=seed.PLANNER_SERVICE_CLASS,
        ogm=OGM(db=graphdb.__class__.from_env()),
        host="127.0.0.1",
        port=8997,
    )

    with pytest.raises(Exception):
        with mw_a.request(
            capability_class=seed.HELLO_CAPABILITY_CLASS,
            operation_class=str(CFC.Operation),
        ) as op:
            pass
    op_iri = op.iri

    # The Operation was reverted: no type, no capability link, no status remain.
    assert not db.triple_exists((op_iri, RDF.type, CFC.Operation))
    assert not db.triple_exists((op_iri, CFC.implementsCapability, cap_instance))
    assert not db.triples_get(sub=op_iri, pred=SVC.operationStatus)
