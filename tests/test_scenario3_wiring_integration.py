"""Scenario 3 wiring: graph -> recognition -> connectors -> served payload (#40).

Live GraphDB plus a live in-process MQTT broker. This is the ticket's real acceptance surface:
the middleware reads the seeded TransferUnit out of the graph, recognises which of its
properties are interface-accessible parameters, builds the right number of connectors in the
right directions, and — the regression that matters — serves a payload that carries no
connection metadata whatever the flavour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from aas_middleware.middleware.sync.synced_connector import SyncDirection
from kapps_ogm import OGM
from kapps_ogm.utils.class_scope import ClassScope

from kapps_semantic_middleware.connectors.mqtt_binding import MQTTBinding
from kapps_semantic_middleware.connectors.semantic import SemanticConnectorRegistry
from kapps_semantic_middleware.connectors.wiring import plan_wiring
from kapps_semantic_middleware.projection import carries_southbound
from kapps_semantic_middleware.vocabulary import INF, AccessMode

from conftest import requires_graphdb  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import seed  # noqa: E402


@pytest.fixture
def scenario3(graphdb):
    """A seeded scenario 3 and an OGM over it."""
    ogm = OGM(db=graphdb)
    seed.seed_scenario3(graphdb, ogm)
    return graphdb, OGM(db=graphdb)


@pytest.fixture
def unit_scope():
    """The consumer's view: rooted at the TransferUnit, reaching its parameters.

    Two levels, because a TransferUnit's parameters hang off its belts and barriers. A view
    belongs to its consumer and is configured in embedding code, not in the ontology
    (ADR 0018).
    """
    return ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )


def _plan(ogm, unit_scope, **kwargs):
    return plan_wiring(
        ogm=ogm,
        resource_iri=seed.TRANSFER_UNIT_1,
        class_scope=unit_scope,
        registry=SemanticConnectorRegistry([MQTTBinding]),
        **kwargs,
    )


@requires_graphdb
class TestRecognition:
    """Four parameters, recognised from the graph by their interface property."""

    def test_recognises_all_four_parameters(self, scenario3, unit_scope):
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope)

        assert len(plan.bindings) == 4
        assert {str(b.resource_iri) for b in plan.bindings} == {
            str(seed.CONVEYOR_BELT_LEFT),
            str(seed.CONVEYOR_BELT_RIGHT),
            str(seed.LIGHT_BARRIER_FRONT),
            str(seed.LIGHT_BARRIER_BACK),
        }

    def test_reads_each_parameter_access_mode_from_the_graph(self, scenario3, unit_scope):
        """Belts are settable control variables; barriers are read-only sensors."""
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope)
        modes = {str(b.resource_iri): b.access_mode for b in plan.bindings}

        assert modes[str(seed.CONVEYOR_BELT_LEFT)] == AccessMode.READWRITE
        assert modes[str(seed.LIGHT_BARRIER_FRONT)] == AccessMode.READ

    def test_reads_the_connection_metadata_off_the_parameter_node(
        self, scenario3, unit_scope
    ):
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope)
        left = next(
            b for b in plan.bindings if str(b.resource_iri) == str(seed.CONVEYOR_BELT_LEFT)
        )

        assert left.get(INF.hasMQTTTopic) == "TransferUnit1/ConveyorBelt/left/speed"
        assert left.get(INF.hasMQTTSetTopic) == "TransferUnit1/ConveyorBelt/left/speed_set"
        assert left.get(INF.hasMQTTBrokerIP) == seed.MQTT_BROKER_IP

    def test_binds_to_the_complex_property_not_hasvalue(self, scenario3, unit_scope):
        """ConnectionInfo has three levels and field_id is a plain getattr, so the parameter
        node is the deepest addressable thing (ADR 0017 / ADR 0023)."""
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope)

        assert {b.field_id for b in plan.bindings} == {
            seed.TU_HAS_CONVEYOR_SPEED.lined,
            seed.TU_IS_OCCUPIED.lined,
        }
        assert INF.hasValue.lined not in {b.field_id for b in plan.bindings}


@requires_graphdb
class TestRegistrationCount:
    """4 parameters -> 4 bindings -> 6 connectors -> 6 topics (ADR 0023)."""

    def test_a_controller_builds_six_connectors(self, scenario3, unit_scope):
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope, flavour=SyncDirection.BIDIRECTIONAL)

        assert len(plan.registrations) == 6
        topics = {r.connector.topic for _, r in plan.registrations}
        assert topics == {
            "TransferUnit1/ConveyorBelt/left/speed",
            "TransferUnit1/ConveyorBelt/left/speed_set",
            "TransferUnit1/ConveyorBelt/right/speed",
            "TransferUnit1/ConveyorBelt/right/speed_set",
            "TransferUnit1/LightBarrier/front/occupied",
            "TransferUnit1/LightBarrier/back/occupied",
        }

    def test_a_monitor_builds_four_and_can_drive_nothing(self, scenario3, unit_scope):
        """TO_PERSISTENCE: live values, structurally unable to write (ADR 0022)."""
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope, flavour=SyncDirection.TO_PERSISTENCE)

        assert len(plan.registrations) == 4
        assert all(
            r.sync_direction is SyncDirection.TO_PERSISTENCE for _, r in plan.registrations
        )
        assert not any("_set" in r.connector.topic for _, r in plan.registrations)

    def test_an_inspector_builds_none(self, scenario3, unit_scope):
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope, autoregister=False)

        assert plan.registrations == []

    def test_an_inspector_still_recognises_every_parameter(self, scenario3, unit_scope):
        """The flag gates wiring, never recognition. Skipping recognition would make every
        parameter node ordinary data, and an inspector would serve broker addresses
        northbound (ADR 0020 / ADR 0028)."""
        _, ogm = scenario3

        plan = _plan(ogm, unit_scope, autoregister=False)

        assert len(plan.bindings) == 4


@requires_graphdb
class TestNorthboundProjection:
    """The regression that matters: no flavour ever serves connection metadata."""

    def _served(self, ogm, plan):
        node = ogm.fetch(
            instance_iri=seed.TRANSFER_UNIT_1, **plan.northbound_fetch_kwargs()
        )
        return node.instance.model_dump()

    def test_the_unpruned_spec_would_have_leaked(self, scenario3, unit_scope):
        """Guards the premise. If this ever stops leaking, the OGM gained a merge-depth
        knob and ADR 0028's prune can retire."""
        _, ogm = scenario3
        full = ogm.get_class_spec(
            class_iri=seed.TRANSFER_UNIT_CLASS, class_scope=unit_scope
        )

        leaked = ogm.fetch(
            instance_iri=seed.TRANSFER_UNIT_1,
            class_spec=full,
            class_scope=unit_scope,
            materialize=True,
        )

        assert carries_southbound(
            leaked.instance.model_dump(),
            SemanticConnectorRegistry([MQTTBinding]).southbound_properties(),
        )

    @pytest.mark.parametrize(
        "flavour, autoregister",
        [
            (SyncDirection.BIDIRECTIONAL, True),  # controller
            (SyncDirection.TO_PERSISTENCE, True),  # monitor
            (SyncDirection.BIDIRECTIONAL, False),  # inspector
        ],
    )
    def test_no_flavour_serves_connection_metadata(
        self, scenario3, unit_scope, flavour, autoregister
    ):
        _, ogm = scenario3
        plan = _plan(ogm, unit_scope, flavour=flavour, autoregister=autoregister)

        served = self._served(ogm, plan)

        assert carries_southbound(served, plan.southbound_properties) == set()
        assert "127.0.0.1" not in str(served)

    def test_all_three_flavours_serve_identical_payloads(self, scenario3, unit_scope):
        """#40's stated regression test."""
        _, ogm = scenario3

        controller = self._served(ogm, _plan(ogm, unit_scope))
        monitor = self._served(
            ogm, _plan(ogm, unit_scope, flavour=SyncDirection.TO_PERSISTENCE)
        )
        inspector = self._served(ogm, _plan(ogm, unit_scope, autoregister=False))

        assert controller == monitor == inspector

    def test_the_projection_keeps_northbound_content(self, scenario3, unit_scope):
        """An empty projection would technically pass the leak test and be useless."""
        _, ogm = scenario3
        plan = _plan(ogm, unit_scope)

        served = str(self._served(ogm, plan))

        assert INF.accessMode.lined in served
        assert seed.TU_HAS_UNIT.lined in served
        assert INF.hasValue.lined in served
