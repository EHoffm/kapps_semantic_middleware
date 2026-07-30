"""Service identity is per middleware instance, not per resource (ADR 0022, #47).

`mint_service_iri` used to be a pure function of the resource, so two middlewares bound to one
resource shared a single `svc:Service` node: the second registration overwrote the first's
`svc:address`, both heartbeated the same `svc:lastHeartbeat`, and either shutdown deregistered the
survivor. None of it failed loudly. These tests pin the two properties that fix it — a
discriminator **stable across restarts of the same deployment** and **distinct between concurrent
instances** — and the discovery helper that replaces reconstructing a service IRI from a resource
IRI.

The unit tests are pure logic; the integration tests need a live GraphDB and are skipped when the
`GRAPHDB_*` env vars are absent.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from graph_db_interface import IRI

from kapps_ogm import OGM
from kapps_semantic_middleware import SemanticMiddleware
from kapps_semantic_middleware.registration import (
    mint_service_iri,
    services_of_resource,
    sweep_stale_services,
    update_heartbeat,
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

# Ports nothing else in the suite binds. No server is started here — the middlewares register
# through `_register_service` directly — but the port still decides the address, and the address
# is what discriminates the service node.
PORT_A = 8971
PORT_B = 8972

RESOURCE = IRI(seed.HELLO_RESOURCE)
ADDR_A = f"http://127.0.0.1:{PORT_A}"
ADDR_B = f"http://127.0.0.1:{PORT_B}"


class TestMintServiceIri:
    """The minted IRI: distinct per instance, stable per deployment, and still reversible."""

    def test_two_instances_on_one_resource_get_distinct_iris(self):
        assert mint_service_iri(RESOURCE, ADDR_A) != mint_service_iri(RESOURCE, ADDR_B)

    def test_the_same_deployment_reuses_its_iri(self):
        # The restart case: a returning instance must re-adopt its node rather than orphan it.
        assert mint_service_iri(RESOURCE, ADDR_A) == mint_service_iri(RESOURCE, ADDR_A)

    def test_the_iri_is_rooted_at_the_resource(self):
        # Which resource a service belongs to stays readable off the IRI alone, as before.
        assert str(mint_service_iri(RESOURCE, ADDR_A)).startswith(f"{RESOURCE}_service_")

    def test_trivial_address_spellings_collapse_to_one_iri(self):
        # A trailing slash or a differently-cased host is the same deployment; minting two nodes
        # for it would resurrect exactly the orphaning this change exists to prevent.
        assert (
            mint_service_iri(RESOURCE, "http://localhost:8000")
            == mint_service_iri(RESOURCE, "http://localhost:8000/")
            == mint_service_iri(RESOURCE, "http://LocalHost:8000")
        )

    def test_the_discriminator_reverses_to_the_address(self):
        # ADR 0021: production IRIs stay back-resolvable, so the discriminator is `IRI.lined`
        # rather than a hash — the instance's address is readable off its own node IRI.
        minted = mint_service_iri(RESOURCE, ADDR_A)
        discriminator = str(minted)[len(f"{RESOURCE}_service_") :]
        assert str(IRI.from_lined(discriminator)) == ADDR_A

    def test_an_address_that_is_not_an_absolute_url_is_rejected(self):
        with pytest.raises(ValueError):
            mint_service_iri(RESOURCE, "8000")


def _hello_instance(graphdb, port: int) -> SemanticMiddleware:
    """A resource-mode middleware on the shared hello resource, distinguished only by its port."""
    return SemanticMiddleware(
        mode="resource",
        resource_iri=seed.HELLO_RESOURCE,
        service_class=seed.HELLO_SERVICE_CLASS,
        ogm=OGM(db=graphdb.__class__.from_env()),
        host="127.0.0.1",
        port=port,
    )


def _two_registered_instances(graphdb) -> tuple[SemanticMiddleware, SemanticMiddleware]:
    """Two instances on one resource, both registered. The scenario ADR 0022 exists for."""
    seed.seed_scenario1(graphdb)
    mw_a = _hello_instance(graphdb, PORT_A)
    mw_b = _hello_instance(graphdb, PORT_B)
    asyncio.run(mw_a._register_service())
    asyncio.run(mw_b._register_service())
    return mw_a, mw_b


@requires_graphdb
class TestTwoInstancesOnOneResource:
    """Two middlewares on one `resource_iri` — a controller and a monitor, in ADR 0022's terms."""

    def test_each_instance_registers_its_own_service(self, graphdb):
        mw_a, mw_b = _two_registered_instances(graphdb)

        assert mw_a.service_iri != mw_b.service_iri
        for mw in (mw_a, mw_b):
            addresses = graphdb.triples_get(sub=mw.service_iri, pred=SVC.address)
            assert [str(t[2]) for t in addresses] == [mw.address]
            assert graphdb.triple_exists((mw.service_iri, SVC.isServiceOf, seed.HELLO_RESOURCE))

    def test_heartbeats_are_independent(self, graphdb):
        mw_a, mw_b = _two_registered_instances(graphdb)
        asyncio.run(mw_a.emit_heartbeat())

        # A shared node would report the resource alive while *either* process lives, which is
        # what stops liveness (ADR 0007) meaning what discovery assumes it means.
        assert len(graphdb.triples_get(sub=mw_a.service_iri, pred=SVC.lastHeartbeat)) == 1
        assert len(graphdb.triples_get(sub=mw_b.service_iri, pred=SVC.lastHeartbeat)) == 0

    def test_stopping_one_leaves_the_other_discoverable_and_alive(self, graphdb):
        mw_a, mw_b = _two_registered_instances(graphdb)
        asyncio.run(mw_b.emit_heartbeat())
        asyncio.run(mw_a._deregister_service())

        assert not graphdb.triples_get(sub=mw_a.service_iri, pred=SVC.address)
        assert graphdb.triples_get(sub=mw_b.service_iri, pred=SVC.address)
        reachable = services_of_resource(OGM(db=graphdb), seed.HELLO_RESOURCE, reachable_only=True)
        assert reachable == [mw_b.service_iri]
        # Discoverable is not the same as alive: the survivor must still hold its own heartbeat,
        # which a shared node could not have expressed (ADR 0007).
        assert len(graphdb.triples_get(sub=mw_b.service_iri, pred=SVC.lastHeartbeat)) == 1

    def test_a_restart_reuses_its_node_rather_than_orphaning_one(self, graphdb):
        mw_a, _ = _two_registered_instances(graphdb)
        asyncio.run(mw_a._deregister_service())

        restarted = _hello_instance(graphdb, PORT_A)
        asyncio.run(restarted._register_service())

        assert restarted.service_iri == mw_a.service_iri
        # Two instances ever existed, so two nodes exist. A third would be an orphan.
        assert len(services_of_resource(OGM(db=graphdb), seed.HELLO_RESOURCE)) == 2

    def test_only_the_stale_instance_is_swept(self, graphdb):
        """A crashed instance goes stale on its own; its sibling keeps its reachability.

        What the watchdog does with the *resource's* stranded Operations once a resource carries
        several Services is a separate question, and a harder one — see #63.
        """
        mw_live, mw_dead = _two_registered_instances(graphdb)
        ogm = OGM(db=graphdb)
        update_heartbeat(ogm, mw_live.service_iri)
        update_heartbeat(
            ogm, mw_dead.service_iri, timestamp=datetime.now(timezone.utc) - timedelta(hours=1)
        )

        swept = sweep_stale_services(ogm, max_age_seconds=60.0)

        assert mw_dead.service_iri in swept and mw_live.service_iri not in swept
        assert not graphdb.triples_get(sub=mw_dead.service_iri, pred=SVC.address)
        assert graphdb.triples_get(sub=mw_live.service_iri, pred=SVC.address)

    def test_services_of_resource_finds_both(self, graphdb):
        mw_a, mw_b = _two_registered_instances(graphdb)

        # Consumers query svc:isServiceOf rather than reconstructing the IRI, and must accept
        # more than one answer.
        assert sorted(services_of_resource(OGM(db=graphdb), seed.HELLO_RESOURCE)) == sorted(
            [mw_a.service_iri, mw_b.service_iri]
        )
