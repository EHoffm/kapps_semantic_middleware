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


@pytest.fixture
def graphdb():
    """A live GraphDB client from the environment, or skip the test."""
    if not _graphdb_env_present():
        pytest.skip("GRAPHDB_* environment variables not set")
    from graph_db_interface import GraphDB

    return GraphDB.from_env()


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
