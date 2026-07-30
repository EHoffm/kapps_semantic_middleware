"""Recursive REST router integration: route generation from the real materialized tree.

``tests/test_recursive_rest_router.py`` proves the router's logic against hand-built pydantic
models. That cannot prove the router works on the tree the **OGM actually materializes** — the
shape it walks (which nodes carry an ``id``, what the field annotations really are, how the
parameter blanknodes come back) is exactly what a hand-built fixture assumes rather than tests.
This file closes that gap: it generates routes from a real seeded TransferUnit and asserts the
paths that come out.

Scope honestly: this covers **route generation from the real materialized tree**. Write semantics
are covered precisely by the unit tests, where the persistence connector is observable; driving a
live PUT here would reach connectors that are registered but not connected (no ASGI lifespan has
run), which would test the framework's failure handling rather than this router.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from graph_db_interface import IRI

from aas_middleware.middleware.sync.synced_connector import SyncDirection
from kapps_ogm import OGM
from kapps_ogm.utils.class_scope import ClassScope

from kapps_semantic_middleware import Mode, SemanticMiddleware

from conftest import methods_at, requires_graphdb  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import seed  # noqa: E402


@pytest.fixture
def scenario3_ogm(graphdb):
    """A seeded scenario 3 and a fresh OGM over it.

    Function-scoped, and that is load-bearing however tempting the ~80 round trips a seed
    costs are: several tests here could add interface metadata with a raw SPARQL INSERT to
    prove a declared term survives the read. Sharing one seed across the module lets those
    writes leak forward — an envelope path inserted by one test puts a later test's formatter
    into envelope mode, and it then reads a raw scalar as an unobserved payload.
    """
    seed.seed_scenario3(graphdb, OGM(db=graphdb))
    # A *fresh* OGM, deliberately not the one that seeded: the seeding client carries state
    # from its own writes, and a test that plans a wiring must read the graph the way a
    # cold middleware would.
    return graphdb, OGM(db=graphdb)


def _unit_view() -> ClassScope:
    """The consumer's view of a TransferUnit: the unit, its components, their parameters.

    Two levels, because a TransferUnit's parameters hang off its belts and barriers. A view
    belongs to its consumer and is configured here in embedding code rather than in the
    ontology (ADR 0018) — the ontology cannot know how deep any particular consumer cares to
    look.
    """
    return ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )


def _model_name(mw: SemanticMiddleware, ogm: OGM) -> str:
    """Derive the materialized model class name the way production does.

    ``SemanticMiddleware`` never stores the materialized instance — ``_load_resource_datamodel``
    fetches it into a local and lets it go. This re-fetches via the wiring's northbound kwargs
    to get the class name for building expected route paths.
    """
    node = ogm.fetch(instance_iri=seed.TRANSFER_UNIT_1, **mw._wiring.northbound_fetch_kwargs())
    return type(node.instance).__name__




@requires_graphdb
class TestParameterRoutes:
    """The deep parameter routes exist and have the right verbs per access mode."""

    @pytest.mark.asyncio
    async def test_the_left_belts_speed_is_addressable(self, scenario3_ogm):
        """The deep path for ConveyorBelt/left/hasConveyorSpeed exists and serves GET.

        This is the route the whole ticket exists to create: a parameter nested two levels
        beneath the root instance, reached through a list of belts, then the speed property
        on a specific belt. If this path does not exist, the recursive router failed to walk
        the materialized tree.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        model_name = _model_name(mw, ogm)
        expected_path = (
            f"/{model_name}"
            f"/{IRI(str(seed.TRANSFER_UNIT_1)).lined}"
            f"/{seed.TU_HAS_CONVEYOR_BELT.lined}"
            f"/{IRI(str(seed.CONVEYOR_BELT_LEFT)).lined}"
            f"/{seed.TU_HAS_CONVEYOR_SPEED.lined}"
        )

        assert expected_path in mw._parameter_routes
        assert "GET" in methods_at(mw.app, expected_path)

    @pytest.mark.asyncio
    async def test_a_settable_parameter_gets_a_put(self, scenario3_ogm):
        """The conveyor speed path also serves PUT, because the seeded parameter is readwrite.

        Access mode is read from the graph (``inf:accessMode`` on the parameter node), and
        verb gating is per individual: one belt may be ``readwrite`` while a barrier on the
        same unit is ``read``. A PUT to a read-only parameter returns 405 because the route
        does not exist; FastAPI handles that automatically. This asserts the readwrite case.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        model_name = _model_name(mw, ogm)
        expected_path = (
            f"/{model_name}"
            f"/{IRI(str(seed.TRANSFER_UNIT_1)).lined}"
            f"/{seed.TU_HAS_CONVEYOR_BELT.lined}"
            f"/{IRI(str(seed.CONVEYOR_BELT_LEFT)).lined}"
            f"/{seed.TU_HAS_CONVEYOR_SPEED.lined}"
        )

        assert "PUT" in methods_at(mw.app, expected_path)

    @pytest.mark.asyncio
    async def test_a_read_only_sensor_gets_no_put(self, scenario3_ogm):
        """The light barrier path serves GET and **not** PUT.

        A write to a light barrier must be a 405 from a route that does not exist. The seeded
        barrier's ``inf:accessMode`` is ``READ``, so the router must not generate a PUT handler
        for it. This guards against the regression where access mode was ignored and every
        parameter became writable.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        model_name = _model_name(mw, ogm)
        expected_path = (
            f"/{model_name}"
            f"/{IRI(str(seed.TRANSFER_UNIT_1)).lined}"
            f"/{seed.TU_HAS_LIGHT_BARRIER.lined}"
            f"/{IRI(str(seed.LIGHT_BARRIER_FRONT)).lined}"
            f"/{seed.TU_IS_OCCUPIED.lined}"
        )

        assert expected_path in mw._parameter_routes
        assert "GET" in methods_at(mw.app, expected_path)
        assert "PUT" not in methods_at(mw.app, expected_path)


@requires_graphdb
class TestRecursionTermination:
    """The walk stops at parameters and does not descend further."""

    @pytest.mark.asyncio
    async def test_no_route_is_generated_below_a_parameter(self, scenario3_ogm):
        """No generated route path starts with another generated route path plus ``/``.

        Recursion terminates at COMPLEX properties because RDF has no properties-about-properties:
        metadata about a conveyor speed (its unit, its MQTT topic) is modelled as a blanknode
        hanging off the parameter property. That blanknode materializes as an ``AnonymousClass``
        with no ``id`` — not ``Identifiable``, therefore never routable. Treating the blanknode
        dict as the atomic element makes the id-less problem disappear. This asserts that no
        route descends below a parameter.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        param_paths = mw._parameter_routes

        for i, path_a in enumerate(param_paths):
            for j, path_b in enumerate(param_paths):
                if i != j:
                    assert not path_b.startswith(path_a + "/"), (
                        f"Route {path_b} descends below parameter route {path_a}"
                    )


@requires_graphdb
class TestCoverage:
    """The walk reaches everything recognition found."""

    @pytest.mark.asyncio
    async def test_every_recognised_parameter_is_addressable(self, scenario3_ogm):
        """The number of generated parameter routes equals the number of bindings, and every
        binding's ``field_id`` appears as the last segment of some generated path.

        This is the claim that the tree walk reaches everything recognition found — the failure
        mode where the walk silently misses a branch. Recognition happens from the graph; routing
        happens from the materialized instance. If the instance tree differs from what recognition
        expects, a parameter could be recognised but unreachable via REST.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        param_routes = mw._parameter_routes

        assert len(param_routes) == len(mw._wiring.bindings)

        binding_field_ids = {b.field_id for b in mw._wiring.bindings}
        route_last_segments = {r.split("/")[-1] for r in param_routes}

        assert binding_field_ids == route_last_segments

    @pytest.mark.asyncio
    async def test_the_top_level_crud_still_exists(self, scenario3_ogm):
        """The framework's top-level route for the TransferUnit model is still present.

        The local router calls the framework generator before adding its own routes. This guards
        the "scenarios 1 and 2 are unaffected" criterion at the route level: adding recursive
        parameter routes must not break the existing top-level CRUD that other consumers rely on.
        """
        graphdb, ogm = scenario3_ogm

        mw = SemanticMiddleware(
            mode=Mode.RESOURCE,
            resource_iri=seed.TRANSFER_UNIT_1,
            service_class=f"{seed.TU_NS}TransferUnitService",
            ogm=ogm,
            host="127.0.0.1",
            port=8996,
            class_scope=_unit_view(),
            connector_sync_direction=SyncDirection.BIDIRECTIONAL,
            heartbeat_interval=None,
        )
        await mw._load_resource_datamodel()

        model_name = _model_name(mw, ogm)
        # The framework parameterises the item: `/{Model}/{item_id}`, matched at request time.
        # The parameter routes below it are literal instead, because the verb gate is
        # per individual (ADR 0017) — so the two levels legitimately encode ids differently,
        # and a consumer derives the deep paths structurally from a GET rather than building
        # them by hand (#43).
        top_level_path = f"/{model_name}/{{item_id}}"

        assert any(r.path == top_level_path for r in mw.app.routes)
