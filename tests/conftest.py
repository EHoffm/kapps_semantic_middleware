"""Shared pytest fixtures.

Integration tests run against a real GraphDB (matching the convention of the
sibling repos, which test against a live triple store rather than a mock). They
are skipped automatically when the ``GRAPHDB_*`` environment variables are not
set, so the pure-logic unit tests still run anywhere.
"""

from __future__ import annotations

import os

import pytest

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
