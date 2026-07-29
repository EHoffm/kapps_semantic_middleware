"""Recognition and wiring: turning a resource's ClassSpec into connector registrations.

This is the step ADR 0023 calls "registering from the knowledge graph". It runs at
**construction**, not during ``on_start_up``, and the reason is sharp: ``lifespan`` calls
``connect()`` on everything in the connection registry *before* running ``on_start_up``
callbacks, and ``initiate_sync`` — what ``add_synced_connector`` defers — starts
``run_receive()`` but never calls ``connect()``. A connector registered while materializing
the datamodel therefore never connects: the client stays ``None``, the listener task never
starts, its queue is never fed, and ``receive()`` blocks forever. Outbound would limp along,
because ``consume()`` reconnects on failure. The failure is one-directional and silent.

Registering at construction avoids it with no out-of-band lifecycle call, and is possible
because everything a ``ConnectionInfo`` needs comes from the ClassSpec and the graph.

Two shapes come out of here, and both are needed (ADR 0028):

- the **full** spec, which the bindings read to find broker addresses and topics, and
- the **pruned** spec, which is what gets served northbound.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from aas_middleware.middleware.sync.synced_connector import SyncDirection
from graph_db_interface import IRI

from kapps_semantic_middleware.connectors.semantic import (
    ParameterBinding,
    Registration,
    SemanticConnectorRegistry,
    normalize_metadata,
    resolve_direction,
)
from kapps_semantic_middleware.projection import prune_southbound

logger = logging.getLogger(__name__)

EXPLICIT_GRAPH = "FROM <http://www.ontotext.com/explicit>"
"""Restrict a query to asserted triples.

Not an ontology term, so it does not belong in ``vocabulary.py`` — it names a GraphDB
*feature*, the pseudo-graph of explicit statements. It is a constant rather than three inline
copies because every recognition query needs it for the same reason: the default graph
includes materialised inference, and a parameter node's only types are anonymous restriction
nodes that exist by inference alone (ADR 0020). Counting or reading without this returns
inferred triples and inflates every result.
"""


@dataclass
class WiringPlan:
    """What recognition found, and what the caller should do about it."""

    northbound_spec: Any
    """The pruned ClassSpec, safe to materialize and serve."""

    class_scope: Any
    """The scope the specs were resolved under.

    Kept because a fetch needs **both**: ``_fetch_object_property`` decides whether a nested
    individual is hydrated or fetched as a bare reference from the *class_scope*
    (``as_reference = nested_class_scope is None``), not from whether the spec it was handed
    has a ``nested``. Passing only the pruned spec yields belts and barriers with empty
    parameters. Use :func:`northbound_fetch_kwargs` rather than restating this."""

    bindings: List[ParameterBinding]
    """Every recognised interface-accessible parameter. Populated for every flavour,
    including one that wires nothing — recognition is never gated (ADR 0020, ADR 0028)."""

    registrations: List[Tuple[ParameterBinding, Registration]]
    """The connector registrations to perform. Empty when the flavour wires nothing."""

    southbound_properties: frozenset
    """The prune set that was applied, kept for assertions and diagnostics."""

    def northbound_fetch_kwargs(self) -> Dict[str, Any]:
        """The arguments that materialize this resource's northbound view."""
        return {
            "class_spec": self.northbound_spec,
            "class_scope": self.class_scope,
            "materialize": True,
        }


def plan_wiring(
    *,
    ogm: Any,
    resource_iri: IRI,
    class_scope: Any,
    resource_class: Optional[IRI] = None,
    registry: SemanticConnectorRegistry,
    flavour: SyncDirection = SyncDirection.BIDIRECTIONAL,
    autoregister: bool = True,
) -> WiringPlan:
    """Resolve a resource's parameters and decide what to connect.

    ``autoregister`` gates only the registrations. The spec, the projection and the recognised
    bindings are produced either way, because an inspector that skipped recognition would
    treat every parameter node as ordinary data and serve its broker address — the
    least-privileged flavour would leak the most (ADR 0028).
    """
    southbound = registry.southbound_properties()

    resource_class = resource_class or _class_of(ogm, resource_iri)
    full_spec = ogm.get_class_spec(class_iri=resource_class, class_scope=class_scope)
    northbound_spec = prune_southbound(full_spec, southbound)

    bindings = _recognise(
        ogm=ogm, resource_iri=resource_iri, spec=full_spec, registry=registry
    )

    registrations: List[Tuple[ParameterBinding, Registration]] = []
    if autoregister:
        for binding in bindings:
            direction = resolve_direction(binding.access_mode, flavour)
            for registration in binding.descriptor.build(binding, direction):
                registrations.append((binding, registration))
    else:
        logger.info(
            "autoregister_connectors=False: recognised %d parameter(s) on %s and connected "
            "none. The northbound projection still applies.",
            len(bindings),
            resource_iri,
        )

    return WiringPlan(
        northbound_spec=northbound_spec,
        class_scope=class_scope,
        bindings=bindings,
        registrations=registrations,
        southbound_properties=southbound,
    )


def _recognise(
    *,
    ogm: Any,
    resource_iri: IRI,
    spec: Any,
    registry: SemanticConnectorRegistry,
) -> List[ParameterBinding]:
    """Walk a resource's spec and the graph, and pair each parameter with its descriptor.

    Matching is on the **interface property**, not on ``rdf:type``. A parameter node has no
    named type of its own — only anonymous restriction nodes, which exist by inference and so
    never appear in an explicit-graph fetch. The property hierarchy is what survives a
    round trip (ADR 0020).
    """
    bindings: List[ParameterBinding] = []

    for holder_iri, prop_iri, prop_spec in _parameter_properties(
        ogm=ogm, root_iri=resource_iri, spec=spec
    ):
        descriptor = _descriptor_for(ogm=ogm, prop_iri=prop_iri, registry=registry)
        if descriptor is None:
            # Unrecognised complex content is plain data: shown, readable, nothing wired
            # (ADR 0020). Not an error — the graph may well hold structure this middleware
            # has no connector for.
            continue

        metadata = _parameter_metadata(
            ogm=ogm, holder_iri=holder_iri, prop_iri=prop_iri, prop_spec=prop_spec
        )
        if metadata is None:
            continue

        bindings.append(
            ParameterBinding(
                resource_iri=holder_iri,
                parameter_property=IRI(str(prop_iri)),
                # ClassSpec keys arrive as rdflib URIRef, not IRI, so the mangling has to go
                # through a converted copy -- URIRef has no `lined`.
                field_id=IRI(str(prop_iri)).lined,
                metadata=normalize_metadata(metadata),
                descriptor=descriptor,
                node_model_type=prop_spec.nested.to_pydantic_model(),
            )
        )

    return bindings


def _parameter_properties(*, ogm: Any, root_iri: IRI, spec: Any):
    """Yield ``(holder_iri, property_iri, property_spec)`` for every COMPLEX property.

    A COMPLEX property is the deepest addressable thing: ``ConnectionInfo`` has exactly three
    levels and ``field_id`` resolves by plain ``getattr``, so ``inf:hasValue`` — one level
    further down — is unreachable. This is the same atomic unit ADR 0017 reached from the
    routing side (ADR 0023).

    Descends one level through object properties to reach a resource's components, since a
    TransferUnit's parameters hang off its belts and barriers rather than off the unit.
    """
    from kapps_ogm.mapping.property_spec import PropertyValueKind

    for prop_iri, prop_spec in getattr(spec, "properties", {}).items():
        if prop_spec.value_kind is PropertyValueKind.COMPLEX:
            yield root_iri, prop_iri, prop_spec
            continue

        nested = getattr(prop_spec, "nested", None)
        if nested is None:
            continue

        for component_iri in _linked_individuals(ogm, root_iri, prop_iri):
            yield from _parameter_properties(
                ogm=ogm, root_iri=component_iri, spec=nested
            )


def _linked_individuals(ogm: Any, subject: IRI, prop_iri: IRI) -> List[IRI]:
    """The individuals a resource points at through one object property."""
    rows = ogm.db.query(
        f"SELECT ?o {EXPLICIT_GRAPH} "
        f"WHERE {{ <{subject}> <{prop_iri}> ?o . FILTER(isIRI(?o)) }}",
        convert_bindings=True,
    )["results"]["bindings"]
    return [IRI(str(row["o"])) for row in rows]


def _descriptor_for(*, ogm: Any, prop_iri: IRI, registry: SemanticConnectorRegistry):
    """The registered descriptor whose interface property this property specializes.

    Resolution walks ``rdfs:subPropertyOf*``, so ``tu:hasConveyorSpeed`` matches the binding
    registered for ``inf:isInterfaceAccessibleMQTTParameter``. The most specific registered
    match wins: a protocol marker is a subproperty of the generic one, and binding to the
    generic one would leave the middleware without a protocol to speak.
    """
    matches = [
        descriptor
        for descriptor in registry
        if _is_subproperty_of(ogm, prop_iri, descriptor.interface_property)
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    for descriptor in matches:
        specializes_all = all(
            descriptor is other
            or _is_subproperty_of(
                ogm, descriptor.interface_property, other.interface_property
            )
            for other in matches
        )
        if specializes_all:
            return descriptor

    logger.warning(
        "%s matches %d interface properties with no most-specific one (%s); not binding it.",
        prop_iri,
        len(matches),
        ", ".join(str(d.interface_property) for d in matches),
    )
    return None


def _is_subproperty_of(ogm: Any, prop_iri: IRI, ancestor: IRI) -> bool:
    """Whether ``prop_iri`` is ``ancestor`` or specializes it, transitively."""
    return bool(
        ogm.db.query(
            f"ASK {{ <{prop_iri}> "
            f"<http://www.w3.org/2000/01/rdf-schema#subPropertyOf>* <{ancestor}> }}"
        ).get("boolean", False)
    )


def _parameter_metadata(
    *, ogm: Any, holder_iri: IRI, prop_iri: IRI, prop_spec: Any
) -> Optional[Dict[str, Any]]:
    """Read one parameter node's properties straight from the ABox.

    Read from the graph rather than from a materialized model because this runs at
    construction, before any datamodel exists. Only properties the effective shape declares
    are returned: a property the restriction does not declare would never survive a write
    either, so binding to one would produce a connector whose values silently vanish.
    """
    declared = {str(p) for p in getattr(prop_spec.nested, "properties", {})}

    rows = ogm.db.query(
        f"SELECT ?p ?v {EXPLICIT_GRAPH} "
        f"WHERE {{ <{holder_iri}> <{prop_iri}> ?node . ?node ?p ?v }}",
        convert_bindings=True,
    )["results"]["bindings"]

    if not rows:
        logger.warning(
            "%s on %s is interface-accessible but its parameter node is empty; nothing to "
            "bind. Has the resource been provisioned?",
            prop_iri,
            holder_iri,
        )
        return None

    metadata: Dict[str, Any] = {}
    undeclared = set()
    for row in rows:
        prop, value = str(row["p"]), str(row["v"])
        if prop not in declared:
            undeclared.add(prop)
            continue
        metadata.setdefault(prop, []).append(value)

    if undeclared:
        # Naming the property and the restriction that failed to declare it is the whole
        # point: the value would otherwise never flow and the resource would come up
        # silently dead (#40).
        logger.warning(
            "Parameter node of %s on %s carries %s, which the range restriction of %s does "
            "not declare. %s will not be readable or writable through the middleware.",
            prop_iri,
            holder_iri,
            ", ".join(sorted(undeclared)),
            prop_iri,
            "They" if len(undeclared) > 1 else "It",
        )

    return metadata


# Types every individual carries that say nothing about what it *is*. An OGM ClassSpec
# resolved against one of these fails outright, and `owl:NamedIndividual` in particular is
# asserted on everything the OGM writes.
_META_TYPE_NAMESPACES = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
)


def _class_of(ogm: Any, instance_iri: IRI) -> IRI:
    """The individual's asserted domain class, so a caller need not restate what the graph knows.

    An individual carries several ``rdf:type`` assertions and their order is not meaningful,
    so the structural ones are filtered out rather than trusted to sort last — picking
    ``owl:NamedIndividual`` yields a ClassSpec that cannot resolve at all.
    """
    rows = ogm.db.query(
        f"SELECT ?c {EXPLICIT_GRAPH} "
        f"WHERE {{ <{instance_iri}> a ?c . FILTER(isIRI(?c)) }}",
        convert_bindings=True,
    )["results"]["bindings"]

    candidates = [
        IRI(str(row["c"]))
        for row in rows
        if not str(row["c"]).startswith(_META_TYPE_NAMESPACES)
    ]

    if not candidates:
        raise ValueError(
            f"{instance_iri} has no asserted domain rdf:type, so its ClassSpec cannot be "
            f"resolved. Pass resource_class explicitly, or seed the instance first."
        )
    if len(candidates) > 1:
        logger.warning(
            "%s asserts %d domain classes (%s); resolving its ClassSpec against %s. Pass "
            "resource_class explicitly to choose.",
            instance_iri,
            len(candidates),
            ", ".join(str(c) for c in candidates),
            candidates[0],
        )
    return candidates[0]
