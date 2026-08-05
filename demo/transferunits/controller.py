"""The controller is a middleware instance: SPARQL view, fetched datamodels, REST
connectors (#80, ADR 0033).

The controller is a resource-mode middleware instance that holds its own datamodels. It
never speaks raw HTTP itself. Its own driving connectors do that, exactly the way a
device-facing instance's MQTT connectors do (ADR 0022/0023). The Control Expert's five
steps (ADR 0033, ``CONTEXT.md``):

1. ``view()`` runs the caller's own SPARQL query -- the view -- and returns every IRI it
   binds to ``?resource``. The query is the whole view: which class, which liveness join
   (a live resource's Service carries ``svc:address``), and any heuristic that narrows it
   further are authored by the caller. Nothing here assumes a domain class.
2. ``wire_view()`` runs ``ogm.fetch`` per hit and recognizes its interface-accessible
   parameters, exactly like ``SemanticMiddleware.__init__`` does for its own resource --
   except every one of these roots is *someone else's* resource, reached over REST
   (ADR 0033), never MQTT: the registry it recognizes against excludes MQTT on purpose,
   so a unit's own broker stays that unit's own middleware's business.
3. Loading happens in an ``on_start_up`` callback (``_load_view_datamodels``): each hit's
   northbound (pruned) datamodel materializes into ``self.units``, keyed by resource IRI.
   No ``inf:hasMQTT*`` property survives the load (ticket #78's projection).
4. Registration happens in step 2, via ``wire_view()`` -- a plain call the caller makes
   after construction and before the app's lifespan starts (before ``run_server``).
   Connectors must exist before the lifespan connects them (ADR 0023), so wiring cannot
   wait for an async hook.
5. ``push()`` drives an in-place assignment on a loaded datamodel out to its owner. An
   algorithm reads and writes ``self.units[...]`` directly; nothing here or in the
   algorithm's body issues an HTTP call.

The controller still discovers resources by class IRI via ``discover_resources`` (ticket
#43), independent of the view mechanism above, and still derives REST parameter paths
via ``_build_parameter_path`` (moved to ``rest_binding.py``, ticket #77). It registers
itself as a ControlStationService so it appears in its own discovery list.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import anyio
from aas_middleware.middleware.registries import ConnectionInfo
from graph_db_interface import IRI

from kapps_semantic_middleware import Mode, SemanticMiddleware
from kapps_semantic_middleware.connectors.rest_binding import RESTBinding
from kapps_semantic_middleware.connectors.rest_binding import (
    build_parameter_path as _rest_build_parameter_path,
)
from kapps_semantic_middleware.connectors.semantic import SemanticConnectorRegistry
from kapps_semantic_middleware.connectors.wiring import WiringPlan, plan_wiring
from kapps_semantic_middleware.vocabulary import CFC, SVC

logger = logging.getLogger(__name__)

_VIEW_REGISTRY = SemanticConnectorRegistry([RESTBinding])
"""REST only, deliberately excluding MQTT (ADR 0033).

The ontology declares a TransferUnit's parameters MQTT-specific
(``tu:hasConveyorSpeed rdfs:subPropertyOf inf:isInterfaceAccessibleMQTTParameter``), and
recognition always resolves to the *most specific* registered descriptor
(``wiring._descriptor_for``) -- that is a TBox fact, and pruning the fetched instance
data cannot change it. A controller that recognized against ``default_registry`` (which
carries both bindings) would therefore try to dial a unit's own broker directly, exactly
the ad-hoc reach ADR 0033 exists to replace with REST. Excluding MQTT from the registry
used for view wiring is what makes REST the only match; the northbound projection then
independently guarantees no broker metadata survives the fetch either (belt and braces,
not two names for the same mechanism)."""


@dataclass
class ResourceInfo:
    """Metadata about a discovered resource, for listing in discovery.

    Attributes:
        resource_iri: The individual's IRI.
        resource_type: The class IRI (e.g. tu:TransferUnit).
        label: Human-readable label, if present.
        address: The service's svc:address — presence means live, absence means offline.
        last_heartbeat: The service's svc:lastHeartbeat timestamp, if present.
    """

    resource_iri: IRI
    """The individual's IRI."""

    resource_type: IRI
    """The class IRI (e.g. tu:TransferUnit)."""

    label: Optional[str]
    """Human-readable label, if present."""

    address: Optional[str]
    """The service's svc:address. Presence means live. Absence means offline."""

    last_heartbeat: Optional[str]
    """The service's svc:lastHeartbeat timestamp, if present."""

    @property
    def is_live(self) -> bool:
        """Live iff svc:address is present (MVP liveness, ticket #43)."""
        return self.address is not None


class Controller(SemanticMiddleware):
    """A resource-mode middleware that holds its own datamodels (ADR 0033, ticket #80).

    ``view()`` runs the caller's SPARQL query and returns the resource IRIs it binds.
    ``wire_view()`` recognizes each hit's interface-accessible parameters and registers
    a driving REST connector for every one it finds -- reached over REST, never MQTT
    (``_VIEW_REGISTRY`` excludes it). Loading happens on startup: each hit's pruned
    datamodel materializes into ``self.units``, keyed by resource IRI string. An
    algorithm reads and writes those loaded objects directly and calls ``push()`` to
    drive an assignment out -- no HTTP call anywhere in its body; the registered
    connector's own ``consume()`` performs that.

    It also discovers resources by class IRI (``discover_resources``, ticket #43) and
    registers itself as a ControlStationService, so it appears in its own discovery
    list, independent of whatever view it wires.

    Usage::

        controller = Controller(
            resource_iri="http://example.org/ControlStation1",
            service_class=CFC.Resource,
            ogm=ogm,
            host="127.0.0.1",
            port=8080,
        )

        # Step 1: the view is the query. No domain class is named here.
        hits = controller.view(VIEW_QUERY)

        # Steps 2-4: recognize and register a driving connector for every hit. Must
        # run before the app's lifespan starts (before uvicorn's serve()).
        controller.wire_view(hits, class_scope=UNIT_SCOPE)

        # ... uvicorn serves the app; on_start_up loads every hit into self.units ...

        # Step 5: the algorithm assigns to its own objects, then pushes.
        unit = controller.units[str(hits[0])]
        belt = getattr(unit, TU_HAS_CONVEYOR_BELT.lined)[0]
        speed = getattr(belt, TU_HAS_CONVEYOR_SPEED.lined)[0]
        setattr(speed, INF.hasValue.lined, [50.0])
        await controller.push(hits[0])
    """

    def __init__(
        self,
        *,
        resource_iri: str,
        service_class: Optional[str] = None,
        ogm: Any = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        named_graph: Optional[str] = None,
        heartbeat_interval: Optional[float] = 30.0,
        staleness_threshold: float = 90.0,
        activity_feed: bool = False,
        activity_capacity: int = 200,
    ) -> None:
        """Initialize the controller middleware.

        Args:
            resource_iri: The IRI of this control station resource.
            service_class: The Service class IRI. It must be svc:Service or
                a subclass. It defaults to svc:Service itself. Ticket #66's
                fac:ControlStationService is not yet an ontology class in
                this repo, so pass it explicitly once that class exists.
            ogm: The OGM instance for graph interactions.
            host: Host to bind the REST API on.
            port: Port to bind the REST API on.
            named_graph: Named graph for resource data.
            heartbeat_interval: Interval for heartbeat updates.
            staleness_threshold: Threshold for considering a resource stale.
            activity_feed: Whether to enable activity feed.
            activity_capacity: Capacity of the activity feed ring buffer.
        """
        # The controller is a resource-mode instance with its own Service registration.
        # It deliberately does NOT use class_scope or autoregister_connectors because
        # it has no physical device to connect to — it talks REST to other resources.
        #
        # service_class must be svc:Service or a subclass (register_service enforces
        # this against the graph). cfc:Resource, the original default here, is not
        # one, and register_service rejected it outright. svc:Service always passes,
        # since assert_class_registered short-circuits when class_iri == base_iri.
        super().__init__(
            mode=Mode.RESOURCE,
            resource_iri=resource_iri,
            service_class=service_class or str(SVC.Service),
            ogm=ogm,
            host=host,
            port=port,
            named_graph=named_graph,
            heartbeat_interval=heartbeat_interval,
            staleness_threshold=staleness_threshold,
            class_scope=None,  # No device interface to prune
            autoregister_connectors=False,  # No connectors for the controller itself
            activity_feed=activity_feed,
            activity_capacity=activity_capacity,
        )

        # The view mechanism (#80, ADR 0033). `units` holds each view hit's loaded
        # northbound datamodel, keyed by `str(resource_iri)` -- what an algorithm reads
        # and mutates directly. `_view_wirings` is the recognition this instance ran for
        # each hit, kept so the on_start_up callback below knows what to fetch.
        # `_view_load_scheduled` guards against registering that callback twice, should
        # `wire_view` ever be called again.
        self.units: Dict[str, Any] = {}
        self._view_wirings: List[Tuple[IRI, WiringPlan]] = []
        self._view_load_scheduled = False

    def view(self, sparql_query: str) -> List[IRI]:
        """Run the caller's SPARQL query -- the view (ADR 0033 step 1) -- and return
        every IRI it binds to ``?resource``, in result order, deduplicated.

        The query is the whole view. Which class, the liveness join (a live resource's
        Service carries ``svc:address``), and any heuristic that narrows the result
        further are all authored by the caller, in the query text. Nothing here assumes
        a domain class or a column beyond ``?resource`` itself, so no rework here can
        ever compile a domain class into the controller.

        Args:
            sparql_query: A SPARQL ``SELECT`` binding at least ``?resource``.

        Returns:
            The distinct ``?resource`` bindings, in the order the query returned them.
        """
        result = self.ogm.db.query(sparql_query, convert_bindings=True)
        bindings = (
            result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
        )

        resource_iris: List[IRI] = []
        seen: set = set()
        for binding in bindings:
            if "resource" not in binding:
                continue
            iri = IRI(str(binding["resource"]))
            key = str(iri)
            if key in seen:
                continue
            seen.add(key)
            resource_iris.append(iri)
        return resource_iris

    def wire_view(
        self,
        resource_iris: Sequence[Union[str, IRI]],
        *,
        class_scope: Any,
        resource_class: Optional[Union[str, IRI]] = None,
        registry: Optional[SemanticConnectorRegistry] = None,
    ) -> None:
        """Recognize every view hit and register its driving REST connectors (ADR 0033
        steps 2-4).

        Call this once, after ``view()`` and before the app's lifespan starts (before
        ``run_server`` / uvicorn's own ``serve()``). ``SemanticMiddleware.__init__``
        documents why this cannot wait for an ``on_start_up`` hook: ``lifespan`` calls
        ``connect()`` on every registered connector *before* running ``on_start_up``,
        so a connector registered afterwards never connects and its listener never
        starts (ADR 0023). ``_wire_semantic_connectors`` runs from ``__init__`` for
        exactly this reason; this mirrors it for N foreign roots instead of one.

        ``class_scope`` is the Control Expert's own view of one hit's shape (ADR 0018) --
        domain-specific, and deliberately not this method's business to construct.
        ``resource_class`` defaults to ``None``, which lets ``plan_wiring`` read each
        hit's own ``rdf:type`` from the graph rather than take one class for every hit
        on faith.

        ``registry`` defaults to :data:`_VIEW_REGISTRY` (REST only, no MQTT) -- see its
        docstring for why. Fetching and persisting each hit's datamodel is deferred to
        an ``on_start_up`` callback (``_load_view_datamodels``): unlike connector
        registration, nothing about ``ogm.fetch``/``persist`` needs to run before the
        lifespan connects anything.
        """
        registry = registry or _VIEW_REGISTRY

        # Register the loader BEFORE any add_synced_connector call below, and only
        # once, ever. Each add_synced_connector call schedules its own on_start_up
        # callback (`initiate_sync`) that looks up the "resource" persistence connector
        # for this hit's model_id -- a KeyError if it does not exist yet. on_start_up
        # callbacks run in registration order (the same constraint
        # SemanticMiddleware.__init__ documents for its own single-resource wiring), so
        # _load_view_datamodels (which calls persist(), creating that connector) must
        # land in the list first.
        if not self._view_load_scheduled:
            self.add_callback("on_start_up", self._load_view_datamodels)
            self._view_load_scheduled = True

        for resource_iri in resource_iris:
            resource_iri = IRI(str(resource_iri))
            wiring = plan_wiring(
                ogm=self.ogm,
                resource_iri=resource_iri,
                class_scope=class_scope,
                resource_class=IRI(str(resource_class)) if resource_class is not None else None,
                registry=registry,
                flavour=self.connector_sync_direction,
                autoregister=True,
                ensure_transport=self.ensure_transport,
            )
            self._view_wirings.append((resource_iri, wiring))

            for binding, registration in wiring.registrations:
                self.add_synced_connector(
                    connector_id=f"{binding.resource_iri}#{binding.field_id}#{registration.suffix}",
                    connector=registration.connector,
                    model_type=registration.model_type,
                    data_model_name="resource",
                    model_id=str(resource_iri),
                    contained_model_id=str(binding.resource_iri),
                    field_id=binding.field_id,
                    formatter=registration.formatter,
                    sync_role=registration.sync_role,
                    sync_direction=registration.sync_direction,
                )

            logger.info(
                "Wired %d connector(s) across %d parameter(s) on view hit %s",
                sum(1 for _ in wiring.registrations),
                len(wiring.bindings),
                resource_iri,
            )

    async def _load_view_datamodels(self) -> None:
        """Fetch and persist every view hit's northbound datamodel (ADR 0033 step 3).

        Runs once, from ``on_start_up``, after ``wire_view`` has already registered
        each hit's connectors. ``WiringPlan.northbound_fetch_kwargs`` is the same
        pruned fetch ``SemanticMiddleware._load_resource_datamodel`` runs for its own
        resource (ticket #78): the materialized instance carries no ``inf:hasMQTT*``
        property, regardless of what the graph holds for the unit's own middleware.

        ``persist`` registers the "resource" persistence connector each connector
        ``wire_view`` added was built against (keyed by this hit's own IRI as
        ``model_id``), which is what makes ``push()`` and the background read poll able
        to find it.

        One hit's fetch failing (the resource vanished between ``wire_view()`` and
        startup, or a transient graph error) is caught and logged rather than left to
        propagate: an uncaught exception here would abort ``on_start_up`` entirely, and
        take down every *other* hit's loading with it -- one dead unit must not sink the
        whole factory's view (the same "fails visibly rather than silently" standard
        ADR 0033's acceptance criteria hold an already-wired unit to).
        """
        for resource_iri, wiring in self._view_wirings:
            fetch = functools.partial(
                self.ogm.fetch, instance_iri=resource_iri, **wiring.northbound_fetch_kwargs()
            )
            try:
                node = await anyio.to_thread.run_sync(fetch)
            except Exception:
                logger.exception(
                    "View hit %s could not be fetched; not loaded.", resource_iri
                )
                continue
            instance = getattr(node, "instance", None)
            if instance is None:
                logger.warning(
                    "View hit %s has no materializable datamodel; not loaded.", resource_iri
                )
                continue
            await self.persist("resource", instance)
            self.units[str(resource_iri)] = instance

        if self.units:
            logger.info("Loaded %d resource(s) from the view onto this controller.", len(self.units))

    async def push(self, resource_iri: Union[str, IRI]) -> None:
        """Drive an in-place assignment on a loaded view datamodel out to its owner
        (ADR 0033 step 5).

        The algorithm mutates ``self.units[str(resource_iri)]`` directly -- ``setattr``
        on the loaded pydantic tree, the ADR 0033 shape
        (``unit.conveyor_belt_left.speed[0]["inf:hasValue"][0] = 12.4``, mangled field
        names notwithstanding: see the class docstring for the real attribute names). A
        plain Python mutation calls out to nothing on its own, so this re-consumes the
        hit's own persistence connector, which fans the new value out to every synced
        connector sharing it (``PersistedConnector._notify_synced_connectors``) --
        among them the REST connector ``wire_view`` registered, whose own ``consume()``
        performs the PUT. No HTTP call happens here or needs to happen in the caller.

        Args:
            resource_iri: One of the IRIs ``view()`` returned and ``wire_view()`` wired.

        Raises:
            KeyError: ``resource_iri`` was never wired (or the app has not started yet,
                so nothing has been loaded and persisted).
        """
        connection_info = ConnectionInfo(data_model_name="resource", model_id=str(resource_iri))
        connector = self.persistence_registry.get_connection(connection_info)
        model = await connector.provide()
        await connector.consume(model)

    def discover_resources(self, resource_class: Any) -> List[ResourceInfo]:
        """List all individuals of resource_class with their service metadata.

        This is the standard discovery path. It uses ontology traversal, so the
        caller writes no SPARQL. Internally, it walks the ontology graph and finds
        each individual and its linked Service node.

        Args:
            resource_class: The resource class IRI or class object (e.g. tu:TransferUnit).

        Returns:
            List of ResourceInfo with address, heartbeat, and liveness status.
        """
        resource_class_iri = IRI(resource_class) if not isinstance(resource_class, IRI) else resource_class

        results: List[ResourceInfo] = []

        try:
            # Query for all individuals of the resource class that have a Service linked.
            sparql = f"""
            SELECT ?resource ?label ?svc ?addr ?hb WHERE {{
                ?resource a <{resource_class_iri}> .
                OPTIONAL {{ ?svc <{SVC.isServiceOf}> ?resource . }}
                OPTIONAL {{ ?svc <{SVC.address}> ?addr . }}
                OPTIONAL {{ ?svc <{SVC.lastHeartbeat}> ?hb . }}
                OPTIONAL {{ ?resource <http://www.w3.org/2000/01/rdf-schema#label> ?label . }}
            }}
            """
            result = self.ogm.db.query(sparql, convert_bindings=True)
            bindings = (
                result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
            )

            seen_resources = set()
            for binding in bindings:
                # With convert_bindings=True, each binding value is already a converted
                # Python object, such as an IRI or a str. It is not a raw {"value": ...}
                # dict. Index it directly. This matches registration.py's own pattern,
                # for example find_resource_operations.
                resource_iri_str = str(binding["resource"])
                if resource_iri_str in seen_resources:
                    continue
                seen_resources.add(resource_iri_str)

                resource_iri = IRI(resource_iri_str)
                label = binding.get("label")
                address = binding.get("addr")
                last_heartbeat = binding.get("hb")

                results.append(ResourceInfo(
                    resource_iri=resource_iri,
                    resource_type=resource_class_iri,
                    label=str(label) if label is not None else None,
                    address=str(address) if address is not None else None,
                    last_heartbeat=str(last_heartbeat) if last_heartbeat is not None else None,
                ))

        except Exception as e:
            logger.warning("Failed to discover resources of class %s: %s", resource_class_iri, e)
            # Return empty list on error. Discovery is best-effort.

        return results

    def _get_service_info(self, resource_iri: IRI) -> Dict[str, Optional[str]]:
        """Get the service metadata for a resource.

        Queries the graph for the Service linked to this resource via svc:isServiceOf,
        returning address and lastHeartbeat.

        Args:
            resource_iri: The resource's IRI.

        Returns:
            Dict with 'address' and 'lastHeartbeat' keys, both possibly None.
        """
        result: Dict[str, Optional[str]] = {"address": None, "lastHeartbeat": None}

        try:
            # Query for the Service linked to this resource via svc:isServiceOf.
            sparql = f"""
            SELECT ?svc ?addr ?hb WHERE {{
                ?svc <{SVC.isServiceOf}> <{resource_iri}> .
                OPTIONAL {{ ?svc <{SVC.address}> ?addr . }}
                OPTIONAL {{ ?svc <{SVC.lastHeartbeat}> ?hb . }}
            }}
            """
            db_result = self.ogm.db.query(sparql, convert_bindings=True)
            bindings = (
                db_result.get("results", {}).get("bindings", []) if isinstance(db_result, dict) else []
            )

            if bindings:
                binding = bindings[0]
                # Same convert_bindings=True shape as discover_resources. Index directly.
                addr_val = binding.get("addr")
                hb_val = binding.get("hb")

                if addr_val is not None:
                    result["address"] = str(addr_val)
                if hb_val is not None:
                    result["lastHeartbeat"] = str(hb_val)

        except Exception as e:
            logger.debug("Failed to get service info for %s: %s", resource_iri, e)

        return result

    @staticmethod
    def _build_parameter_path(
        resource_class_local_name: str,
        resource_iri: IRI,
        steps: Sequence[Tuple[str, str]],
        terminal_field: str,
    ) -> str:
        """Build the structural REST path for a parameter from known (field, child_id) hops.

        Delegates to ``rest_binding.build_parameter_path`` (ticket #77): the algorithm names
        no domain term and the REST semantic connector needs the identical derivation at
        recognition time, so it moved to ``src/`` rather than being duplicated or rewritten
        (ADR 0033). This wrapper is kept because it is this class's own public surface and
        existing callers address it as ``Controller._build_parameter_path``.

        The caller already knows each hop's child id. This method only assembles path
        segments. It does not search a tree. For a version that searches and
        validates a fetched tree, see _derive_parameter_path.

        Args:
            resource_class_local_name: Fragment of the resource's class IRI (e.g. "TransferUnit").
            resource_iri: The root resource's own IRI.
            steps: Sequence of (field_name, child_id) hops to navigate the tree.
            terminal_field: The final field name (the parameter itself).

        Returns:
            The structural URL path.
        """
        return _rest_build_parameter_path(
            resource_class_local_name, resource_iri, steps, terminal_field
        )

    @staticmethod
    def _derive_parameter_path(
        datamodel_tree: Dict[str, Any],
        resource_class_local_name: str,
        resource_iri: IRI,
        steps: Sequence[Tuple[str, str]],
        terminal_field: str,
    ) -> str:
        """Derive a structural REST URL for a parameter by traversing a fetched datamodel tree.

        Mirrors rest_router.py's _accumulate_routes logic. It operates on a plain
        dict/list JSON tree, not on pydantic models.
        This method checks that every hop's child id exists in the tree, then
        builds the path. Use this method, not _build_parameter_path, when the ids
        come from outside the tree and need a check.

        A terminal parameter is a field whose value is a list of dicts WITHOUT an "id" key
        (they carry hasValue/hasUnit/accessMode instead). A non-terminal field's value is a
        list of dicts WITH "id" keys, and recursion continues into the matching child.

        Args:
            datamodel_tree: The full JSON tree of the resource's datamodel.
            resource_class_local_name: Fragment of the resource's class IRI (e.g. "TransferUnit").
            resource_iri: The root resource's own IRI.
            steps: Sequence of (field_name, child_id) hops to navigate the tree.
            terminal_field: The final field name (the parameter itself).

        Returns:
            The structural URL path.

        Raises:
            ValueError: A step's field is not a list, or its child_id is not present.
        """
        current_level = datamodel_tree
        for field_name, child_id in steps:
            field_value = current_level.get(field_name, [])
            if not isinstance(field_value, list):
                raise ValueError(f"Field {field_name} is not a list in the datamodel tree")

            child_dict = next(
                (item for item in field_value if isinstance(item, dict) and item.get("id") == child_id),
                None,
            )
            if child_dict is None:
                raise ValueError(f"Child with id {child_id} not found under field {field_name}")

            current_level = child_dict

        return Controller._build_parameter_path(
            resource_class_local_name, resource_iri, steps, terminal_field
        )
