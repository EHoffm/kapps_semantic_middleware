"""The semantic-connector seam: binding descriptors and their registry (ADR 0023).

A **semantic connector** is any connector that can register itself from the knowledge graph.
It is realized not as a connector subclass but as a **binding descriptor**: an object naming
the connector class it builds, the interface property it binds to, the connection metadata
its protocol needs, and how to turn one parameter's metadata into one or more
``add_synced_connector`` registrations.

Referencing a ``connector_cls`` rather than subclassing it is the point. ``aas_middleware``
ships about ten connectors — MQTT, OPC-UA, HTTP request and polling, websocket and webhook
client and server, AAS client, model — and root ADR 0001 forbids adding self-registration to
any of them in the sibling repo. A descriptor lets a domain expert make a vendor's connector
semantic without owning or subclassing its source, and lets two registration strategies for
one protocol coexist without sharing an ancestor.

MQTT is the first instance of this seam, not its shape. See ``mqtt_binding.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
)

from aas_middleware.middleware.sync.synced_connector import SyncDirection, SyncRole
from graph_db_interface import IRI

from kapps_semantic_middleware.vocabulary import INF, AccessMode

logger = logging.getLogger(__name__)


def first(value: Any) -> Any:
    """The first element of an OGM multi-valued property, or the value itself.

    Every property on a materialized node is a list, because RDF properties are set-valued.
    Connection metadata is single-valued in practice, so unwrapping here keeps every call
    site from restating it. An empty or absent value yields ``None``.
    """
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def normalize_metadata(metadata: Mapping[Any, Any]) -> Dict[str, Any]:
    """Key a parameter node's properties by the string form of their IRI.

    A metadata mapping reaches a binding either from a ``ClassSpec``-derived dict keyed by
    ``IRI`` or from a materialized model keyed by ``str``. Normalizing once here means no
    binding has to be indifferent to which it got, and no binding has to import ``IRI``
    just to do a lookup.
    """
    return {str(key): value for key, value in metadata.items()}


@dataclass(frozen=True)
class Registration:
    """One ``add_synced_connector`` call, described rather than performed.

    A binding yields these instead of touching the middleware directly, so the seam can be
    tested without a running middleware and so the caller decides whether to actually wire
    them — which is what the ``inspector`` flavour needs (ADR 0022).
    """

    connector: Any
    """A constructed framework connector instance (e.g. ``MqttClientConnector``)."""

    sync_direction: SyncDirection
    """Which way this particular connector moves data."""

    model_type: Type[Any]
    """The persistence type of the bound field, for the framework's own bookkeeping."""

    formatter: Optional[Any] = None
    """Translates between the device payload and the persistence value."""

    sync_role: SyncRole = SyncRole.READ_WRITE
    """Role in the framework's sync bookkeeping; the direction does the real gating."""

    suffix: str = ""
    """Disambiguates the connector id when one binding yields several registrations."""


@dataclass(frozen=True)
class ParameterBinding:
    """One interface-accessible parameter, resolved and ready to wire.

    Everything here comes from the ClassSpec and the graph, never from materialized instance
    data — which is what makes construction-time registration possible (ADR 0023).
    """

    resource_iri: IRI
    """The individual carrying the parameter — a belt, a barrier."""

    parameter_property: IRI
    """The domain property whose range is the parameter node (the COMPLEX property)."""

    field_id: str
    """The mangled attribute name the property has on the generated pydantic model."""

    metadata: Dict[str, Any]
    """The parameter node's own properties, keyed by IRI string, connection metadata
    included. Build it with :func:`normalize_metadata`."""

    descriptor: "BindingDescriptor"
    """The binding descriptor that recognised this parameter."""

    node_model_type: Type[Any]
    """The generated pydantic model for the parameter node itself.

    A formatter needs it to rebuild the node from an inbound scalar, because the framework
    replaces the whole value on ``setattr`` and hands the formatter nothing but the payload
    (ADR 0023). It comes from the **full** spec, not the pruned northbound one — the node the
    binding writes must still be the shape the graph expects."""

    def get(self, prop: IRI) -> Any:
        """The single value of one metadata property, or ``None``."""
        return first(self.metadata.get(str(prop)))

    @property
    def access_mode(self) -> str:
        """The parameter's declared access mode, defaulting to read-only.

        An absent or unrecognised value yields ``read``, so a parameter is never writable by
        accident of omission (ADR 0023).
        """
        raw = self.get(INF.accessMode)
        return raw if raw in AccessMode.ALL else AccessMode.READ


class BindingDescriptor(Protocol):
    """What a semantic connector must declare.

    Deliberately a structural protocol over plain class attributes: a descriptor is
    configuration, and requiring inheritance from a base class would defeat the purpose of
    not owning the connector's source.
    """

    connector_cls: Type[Any]
    """The framework connector class this binding constructs. Never subclassed."""

    interface_property: IRI
    """The ``inf:`` marker property a domain property must be a subproperty of to match."""

    connection_metadata: Tuple[IRI, ...]
    """The properties this protocol reads. Also, exactly, the properties that must never go
    north — the registry takes the union as the projection's prune set (ADR 0028)."""

    @staticmethod
    def build(
        binding: ParameterBinding, direction: SyncDirection
    ) -> Iterable[Registration]:
        """Turn one resolved parameter into the registrations that realize it."""
        ...


class SemanticConnectorRegistry:
    """Maps an interface property to the binding descriptor that serves it.

    Resolution is by the **interface property**, not by ``rdf:type``: a parameter node has no
    named type of its own — only anonymous restriction nodes, which are inferred and so
    absent from an explicit-graph fetch. The property hierarchy is what survives (ADR 0020).

    The registry is built and consulted for **every** flavour, including one that wires
    nothing. Implementing "no connectors" as "no registry" would mean no property is
    recognised as a parameter, the parameter node would become ordinary data and be served
    northbound, and the least-privileged instance would leak the most (ADR 0020, ADR 0028).
    """

    def __init__(self, descriptors: Optional[Sequence[BindingDescriptor]] = None) -> None:
        self._by_property: Dict[str, BindingDescriptor] = {}
        for descriptor in descriptors or ():
            self.register(descriptor)

    def register(self, descriptor: BindingDescriptor) -> BindingDescriptor:
        """Add a descriptor, replacing any earlier one for the same interface property.

        Replacement rather than refusal is deliberate: overriding the built-in MQTT binding
        with a site-specific one is a supported use of the seam, and a domain expert should
        not have to unregister first.
        """
        key = str(descriptor.interface_property)
        existing = self._by_property.get(key)
        if existing is not None and existing is not descriptor:
            logger.info(
                "Replacing the binding registered for %s (%s -> %s)",
                key,
                type(existing).__name__,
                type(descriptor).__name__,
            )
        self._by_property[key] = descriptor
        return descriptor

    def for_interface_property(self, iri: IRI) -> Optional[BindingDescriptor]:
        """The descriptor registered for exactly this interface property, if any."""
        return self._by_property.get(str(iri))

    def southbound_properties(self) -> frozenset:
        """Every property any registered binding reads — the projection's prune set.

        Keyed by IRI string, because a prune compares against ClassSpec keys. This is the
        whole reason the core needs no hardcoded list of protocol terms: a domain expert who
        registers a binding for their own protocol gets their terms projected out for free
        (ADR 0021, ADR 0028).
        """
        return frozenset(
            str(prop)
            for descriptor in self._by_property.values()
            for prop in descriptor.connection_metadata
        )

    def __len__(self) -> int:
        return len(self._by_property)

    def __iter__(self) -> Iterator[BindingDescriptor]:
        return iter(self._by_property.values())


# The registry a SemanticMiddleware gets when it is not handed one. Populated when the
# binding modules are imported, so the MQTT binding is available out of the box while
# remaining an ordinary registration rather than a special case.
default_registry = SemanticConnectorRegistry()


def semantic_connector(cls):
    """Register a binding descriptor class on the default registry.

    Used as a plain decorator on the descriptor class::

        @semantic_connector
        class MQTTBinding:
            connector_cls = MqttClientConnector
            interface_property = INF.isInterfaceAccessibleMQTTParameter
            ...
    """
    default_registry.register(cls)
    return cls


def resolve_direction(access_mode: str, flavour: SyncDirection) -> SyncDirection:
    """The most restrictive of the parameter's access mode and the instance's flavour.

    Neither may widen the other (ADR 0023). A monitor can therefore never drive a writable
    belt, and a controller can never write a read-only sensor — structurally, not by
    convention.

    The read leg is always available; the question is only whether the write leg is. So this
    returns ``BIDIRECTIONAL`` when both sides permit writing, and ``TO_PERSISTENCE``
    (device -> middleware, read-only) otherwise.
    """
    parameter_permits_write = access_mode == AccessMode.READWRITE
    flavour_permits_write = flavour in (
        SyncDirection.BIDIRECTIONAL,
        SyncDirection.FROM_PERSISTENCE,
    )
    if parameter_permits_write and flavour_permits_write:
        return SyncDirection.BIDIRECTIONAL
    return SyncDirection.TO_PERSISTENCE
