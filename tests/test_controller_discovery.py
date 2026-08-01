"""Tests for the controller discovery library (ticket #43).

Tests the Controller class. It checks discovery of resources by class IRI,
with live/offline status. It checks the derivation of a structural REST
path for a parameter. It checks that the controller registers as a
service, and appears in its own discovery list.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from graph_db_interface import IRI
from kapps_ogm import OGM

from kapps_semantic_middleware.controller import Controller, ResourceInfo
from kapps_semantic_middleware.registration import mint_service_iri, register_service
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
    """Seed the graph with scenario 3 data, plus a live Service for the unit.

    seed_scenario3 (map #24) creates one TransferUnit's ABox only. It writes
    no Service, since no real middleware instance runs against it here. A
    real N-unit factory needs the launcher, ticket #66, not yet built. To
    test liveness now, this fixture registers a Service by hand for
    seed.TRANSFER_UNIT_1, the same way a real middleware instance would at
    its own startup (see registration.register_service, and the same
    pattern in test_liveness_integration.py).
    """
    seed.seed_scenario3(ogm.db, ogm)
    address = "http://127.0.0.1:19001"
    register_service(
        ogm,
        resource_iri=seed.TRANSFER_UNIT_1,
        service_iri=mint_service_iri(seed.TRANSFER_UNIT_1, address),
        service_class=SVC.Service,
        address=address,
    )
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
        """The controller writes its own Service, with an address, on startup.

        This calls _register_service directly, the same way
        test_liveness_integration.py does. A real deployment fires it
        through the FastAPI app's lifespan instead.
        """
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18080,  # Use different port to avoid conflicts
        )
        asyncio.run(controller._register_service())

        service_triples = seeded_graph.db.triples_get(
            sub=controller.service_iri, pred=SVC.address
        )
        assert len(service_triples) == 1

    @requires_graphdb
    def test_discovers_transfer_units(self, seeded_graph):
        """Discovering TransferUnits returns the seeded unit.

        seed_scenario3 seeds one TransferUnit (map #24). A real N-unit
        factory needs the launcher, ticket #66, not yet built.
        """
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18081,
        )

        # Import the TransferUnit class IRI from seed module
        tu_class = seed.TRANSFER_UNIT_CLASS

        units = controller.discover_resources(tu_class)

        assert len(units) >= 1

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

        assert len(units) >= 1

        # The seeded_graph fixture registers a Service for TRANSFER_UNIT_1
        live_units = [u for u in units if u.is_live]
        assert len(live_units) >= 1

    @requires_graphdb
    def test_controller_appears_in_own_discovery(self, seeded_graph):
        """The controller appears in its own discovery list, once it registers.

        register_service only writes the Service side (svc:isServiceOf plus
        svc:address). It expects the resource individual to already exist,
        the same way a domain seed writes a TransferUnit before its
        middleware starts. A real factory seed does this for the control
        station too (ticket #66); here, the test does it by hand, with the
        same create_resource helper seed_scenario1 uses.
        """
        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            ogm=seeded_graph,
            port=18083,
        )
        seed.create_resource(seeded_graph.db, IRI(controller.resource_iri), CFC.Resource)
        asyncio.run(controller._register_service())

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
    """Tests for REST interaction with resources.

    These tests need a running middleware instance serving a resource.
    They stay skipped until the launcher (ticket #66) exists to serve one.
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


class TestParameterPathDerivation:
    """Offline tests for _build_parameter_path and _derive_parameter_path.

    No GraphDB and no network. These mirror the fixture style of
    test_recursive_rest_router.py, but walk a plain JSON tree of dicts and
    lists instead of pydantic models — the shape open_resource() returns.
    """

    UNIT_IRI = "https://example.org/tui#TransferUnit1"
    LEFT_BELT_IRI = "https://example.org/tui#ConveyorBelt1_left"
    RIGHT_BELT_IRI = "https://example.org/tui#ConveyorBelt1_right"
    BARRIER_IRI = "https://example.org/tui#LightBarrier1_front"

    @staticmethod
    def _make_tree():
        """A TransferUnit-shaped tree: two belts, each with a speed parameter."""
        return {
            "id": TestParameterPathDerivation.UNIT_IRI,
            "tu:hasConveyorBelt": [
                {
                    "id": TestParameterPathDerivation.LEFT_BELT_IRI,
                    "tu:hasConveyorSpeed": [
                        {"inf:hasValue": [1.5], "inf:accessMode": ["readwrite"]}
                    ],
                },
                {
                    "id": TestParameterPathDerivation.RIGHT_BELT_IRI,
                    "tu:hasConveyorSpeed": [
                        {"inf:hasValue": [2.0], "inf:accessMode": ["readwrite"]}
                    ],
                },
            ],
            "tu:hasLightBarrier": [
                {
                    "id": TestParameterPathDerivation.BARRIER_IRI,
                    "tu:isOccupied": [{"inf:hasValue": [False]}],
                },
            ],
        }

    def test_build_path_matches_recursive_router_shape(self):
        """The built path matches /{Model}/{lined_root}/{field}/{lined_child}/{field_id}.

        This is the same shape test_recursive_rest_router.py's _path() helper
        asserts on the server side (ADR 0017).
        """
        path = Controller._build_parameter_path(
            "TransferUnit",
            IRI(self.UNIT_IRI),
            [("tu:hasConveyorBelt", self.LEFT_BELT_IRI)],
            "tu:hasConveyorSpeed",
        )

        expected = (
            f"/TransferUnit/{IRI(self.UNIT_IRI).lined}"
            f"/tu:hasConveyorBelt/{IRI(self.LEFT_BELT_IRI).lined}"
            f"/tu:hasConveyorSpeed"
        )
        assert path == expected

    def test_sibling_belts_produce_different_paths(self):
        """Two belts under one field yield distinct, non-colliding paths."""
        left_path = Controller._build_parameter_path(
            "TransferUnit",
            IRI(self.UNIT_IRI),
            [("tu:hasConveyorBelt", self.LEFT_BELT_IRI)],
            "tu:hasConveyorSpeed",
        )
        right_path = Controller._build_parameter_path(
            "TransferUnit",
            IRI(self.UNIT_IRI),
            [("tu:hasConveyorBelt", self.RIGHT_BELT_IRI)],
            "tu:hasConveyorSpeed",
        )

        assert left_path != right_path
        assert IRI(self.LEFT_BELT_IRI).lined in left_path
        assert IRI(self.RIGHT_BELT_IRI).lined in right_path
        assert IRI(self.LEFT_BELT_IRI).lined not in right_path
        assert IRI(self.RIGHT_BELT_IRI).lined not in left_path

    def test_derive_validates_child_id_against_tree(self):
        """_derive_parameter_path finds the belt in the tree and builds the same path."""
        tree = self._make_tree()

        path = Controller._derive_parameter_path(
            tree,
            "TransferUnit",
            IRI(self.UNIT_IRI),
            [("tu:hasConveyorBelt", self.LEFT_BELT_IRI)],
            "tu:hasConveyorSpeed",
        )

        expected = Controller._build_parameter_path(
            "TransferUnit",
            IRI(self.UNIT_IRI),
            [("tu:hasConveyorBelt", self.LEFT_BELT_IRI)],
            "tu:hasConveyorSpeed",
        )
        assert path == expected

    def test_derive_raises_on_missing_child_id(self):
        """A child id absent from the tree raises, rather than building a dead path."""
        tree = self._make_tree()

        with pytest.raises(ValueError, match="not found"):
            Controller._derive_parameter_path(
                tree,
                "TransferUnit",
                IRI(self.UNIT_IRI),
                [("tu:hasConveyorBelt", "https://example.org/tui#ConveyorBelt1_ghost")],
                "tu:hasConveyorSpeed",
            )

    def test_extract_local_name_splits_fragment(self):
        """_extract_local_name returns the fragment after '#' from a class IRI."""
        assert Controller._extract_local_name(IRI("https://example.org/tu#TransferUnit")) == "TransferUnit"
