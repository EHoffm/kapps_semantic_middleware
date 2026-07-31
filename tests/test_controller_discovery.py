"""Tests for the controller discovery library (ticket #43).

Tests the Controller class's ability to:
- Discover resources by class IRI with live/offline status
- Open a resource's REST datamodel via GET
- Write to parameter paths via PUT
- Register itself as a service appearing in its own discovery
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from graph_db_interface import IRI
from kapps_ogm import OGM

from kapps_semantic_middleware.controller import Controller, ResourceInfo
from kapps_semantic_middleware.vocabulary import CFC, SVC

requires_graphdb = pytest.mark.skipif(
    not all(
        os.getenv(n)
        for n in (
            "GRAPHDB_URL",
            "GRAPHDB_USERNAME",
            "GRAPHDB_PASSWORD",
            "GRAPHDB_REPOSITORY",
        )
    ),
    reason="GRAPHDB_* environment variables not set; skipping live-GraphDB integration test",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import seed  # noqa: E402


@pytest.fixture
def ogm(graphdb):
    """Create an OGM instance for tests."""
    return OGM(db=graphdb)


@pytest.fixture
def seeded_graph(ogm):
    """Seed the graph with scenario 3 data and return the OGM."""
    seed.seed_scenario3(ogm.db, ogm)
    return ogm


class TestResourceInfo:
    """Tests for the ResourceInfo dataclass."""

    def test_is_live_when_address_present(self):
        """A resource is live iff svc:address is present."""
        info = ResourceInfo(
            resource_iri=IRI("http://example.org/Unit1"),
            resource_type=IRI("http://example.org/TransferUnit"),
            label="Unit 1",
            address="http://127.0.0.1:8001",
            last_heartbeat="2024-01-01T12:00:00Z",
        )
        assert info.is_live is True

    def test_is_offline_when_address_absent(self):
        """A resource is offline when svc:address is absent."""
        info = ResourceInfo(
            resource_iri=IRI("http://example.org/Unit1"),
            resource_type=IRI("http://example.org/TransferUnit"),
            label="Unit 1",
            address=None,
            last_heartbeat=None,
        )
        assert info.is_live is False


class TestControllerDiscovery:
    """Tests for the Controller discovery functionality."""

    @requires_graphdb
    def test_controller_registers_itself(self, seeded_graph):
        """The controller registers as a service on startup."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18080,  # Use different port to avoid conflicts
        )

        # The controller should have registered its service
        assert controller.service_iri is not None
        assert controller.address is not None

    @requires_graphdb
    def test_discovers_transfer_units(self, seeded_graph):
        """Discovering TransferUnits returns both seeded units."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18081,
        )

        # Import the TransferUnit class IRI from seed module
        tu_class = seed.TRANSFER_UNIT_CLASS

        units = controller.discover_resources(tu_class)

        # Should find both seeded units
        assert len(units) >= 2

        # Each unit should have its IRI and type
        for unit in units:
            assert unit.resource_iri is not None
            assert unit.resource_type == tu_class

    @requires_graphdb
    def test_discovered_units_have_service_metadata(self, seeded_graph):
        """Discovered units have svc:address from their Service nodes."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18082,
        )

        tu_class = seed.TRANSFER_UNIT_CLASS
        units = controller.discover_resources(tu_class)

        assert len(units) >= 2

        # At least some units should have addresses (are live)
        live_units = [u for u in units if u.is_live]
        # The seed writes svc:address for each unit
        assert len(live_units) >= 2

    @requires_graphdb
    def test_controller_appears_in_own_discovery(self, seeded_graph):
        """The controller appears in its own discovery list."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18083,
        )

        # Discover resources of type cfc:Resource (the controller's own type)
        resources = controller.discover_resources(CFC.Resource)

        # The controller should find itself
        controller_found = False
        for resource in resources:
            if resource.resource_iri == controller.resource_iri:
                controller_found = True
                assert resource.is_live is True
                assert resource.address == controller.address
                break

        assert controller_found, "Controller should appear in its own discovery"


class TestControllerRestInteraction:
    """Tests for REST interaction with discovered resources.

    These tests require a running middleware instance serving a resource.
    They are marked to be skipped unless the full demo environment is available.
    """

    @pytest.mark.skip(reason="Requires running middleware instance")
    async def test_open_resource_returns_datamodel(self):
        """Opening a resource returns its full datamodel tree."""
        # This would require a running middleware at a known URL
        pass

    @pytest.mark.skip(reason="Requires running middleware instance")
    async def test_set_parameter_writes_single_field(self):
        """Setting a parameter does exactly one PUT to the field path."""
        # This would require a running middleware at a known URL
        pass

    @pytest.mark.skip(reason="Requires running middleware instance")
    async def test_get_parameter_reads_single_field(self):
        """Getting a parameter does exactly one GET to the field path."""
        # This would require a running middleware at a known URL
        pass


class TestGetServiceInfo:
    """Tests for the _get_service_info helper method."""

    @requires_graphdb
    def test_gets_address_from_service(self, seeded_graph):
        """_get_service_info returns svc:address for a resource with a Service."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18084,
        )

        # Get info for one of the seeded transfer units
        service_info = controller._get_service_info(seed.TRANSFER_UNIT_1)

        # The seed writes svc:address for each unit
        assert service_info.get("address") is not None

    @requires_graphdb
    def test_returns_none_for_resource_without_service(self, seeded_graph):
        """_get_service_info returns None values for resources without Services."""
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18085,
        )

        # Create a resource that has no Service linked
        fake_iri = IRI("http://example.org/FakeResource")

        service_info = controller._get_service_info(fake_iri)

        assert service_info["address"] is None
        assert service_info["lastHeartbeat"] is None