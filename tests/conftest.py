"""Shared pytest fixtures.

Integration tests run against a real GraphDB (matching the convention of the
sibling repos, which test against a live triple store rather than a mock). They
are skipped automatically when the ``GRAPHDB_*`` environment variables are not
set, so the pure-logic unit tests still run anywhere.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

REQUIRED_GRAPHDB_ENV = (
    "GRAPHDB_URL",
    "GRAPHDB_USERNAME",
    "GRAPHDB_PASSWORD",
    "GRAPHDB_REPOSITORY",
)


def _graphdb_env_present() -> bool:
    return all(os.getenv(name) for name in REQUIRED_GRAPHDB_ENV)


requires_graphdb = pytest.mark.skipif(
    not _graphdb_env_present(),
    reason="GRAPHDB_* environment variables not set; skipping live-GraphDB integration test",
)


def pytest_collection_modifyitems(items):
    """Mark every test that reaches the triple store as ``live``.

    Derived from the fixture graph rather than written on each test, so the marker cannot
    drift out of step with what a test actually needs. ``-m 'not live'`` then selects the
    tests that need no network at all.
    """
    for item in items:
        if "graphdb" in item.fixturenames:
            item.add_marker("live")


def methods_at(app, path: str) -> set:
    """Every HTTP method served at `path`, unioned across routes.

    A parameter route's GET and PUT are two separate `APIRoute` objects that happen to share a
    path, so picking the first match and reading its `.methods` sees only whichever verb was
    mounted first. That makes a "no PUT here" assertion pass whether or not a PUT exists --
    exactly what the read-only tests are meant to prove. It has already caught one false pass;
    it lives here so the offline and live router tests cannot drift apart on it.
    """
    return {
        method
        for route in app.routes
        if getattr(route, "path", None) == path
        for method in route.methods
    }


@pytest.fixture(scope="session")
def graphdb():
    """A live GraphDB client from the environment, or skip the test.

    Session-scoped: constructing a client costs a login round trip plus a repository
    listing, and the client carries no per-test state — only a growing set of minted
    blank-node ids, which is a collision guard that is happier the longer it lives.
    Tests that need a clean *graph* re-seed it; that is separate from the client.
    """
    if not _graphdb_env_present():
        pytest.skip("GRAPHDB_* environment variables not set")
    from graph_db_interface import GraphDB

    db = GraphDB.from_env()
    yield db
    db.close()


@pytest.fixture
def unit_scope():
    """The consumer's view of a scenario-3 TransferUnit, rooted at the unit.

    Two levels, because a TransferUnit's parameters hang off its belts and barriers. A view
    belongs to its consumer and is configured in embedding code rather than in the ontology
    (ADR 0018), so it is stated once here rather than in each test that needs a wired unit.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    import seed
    from kapps_ogm.utils.class_scope import ClassScope

    return ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )


MQTT_TEST_PORT = 18831
"""Not 1883: a developer machine may already run a broker there, and a test that silently
joined it would pass against the wrong state and leak its topics into someone's session."""


@pytest_asyncio.fixture
async def mqtt_broker():
    """A real MQTT broker on 127.0.0.1, in-process, for the duration of one test.

    ``amqtt`` is a pure-Python broker, so this needs no ``mosquitto`` and no root — which
    matters because installing a system broker is exactly what a CI runner and a fresh
    checkout cannot assume. The round trip it serves is genuinely live: real sockets, real
    publish and subscribe, the same ``aiomqtt`` client the framework connector uses.
    """
    from amqtt.broker import Broker

    broker = Broker(
        {
            "listeners": {
                "default": {
                    "type": "tcp",
                    "bind": f"127.0.0.1:{MQTT_TEST_PORT}",
                    "max_connections": 100,
                }
            },
            "sys_interval": 0,
            "auth": {"allow-anonymous": True},
            "topic-check": {"enabled": False},
        }
    )
    await broker.start()
    try:
        yield f"127.0.0.1:{MQTT_TEST_PORT}"
    finally:
        await broker.shutdown()
