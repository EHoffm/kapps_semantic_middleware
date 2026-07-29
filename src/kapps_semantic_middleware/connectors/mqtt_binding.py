"""The MQTT semantic connector: the first instance of the binding seam (ADR 0023).

A parameter is reached over MQTT when its domain property is a subproperty of
``inf:isInterfaceAccessibleMQTTParameter``. The parameter node then carries a broker address,
a read topic, and — if it is settable — a set topic.

**Two connectors per settable parameter, one ConnectionInfo.** ``MqttClientConnector`` takes a
single topic and its ``consume()`` publishes to the topic it subscribed to, so it physically
cannot serve a read topic plus a distinct set topic. ``ConnectionRegistry.connections`` is
``Dict[ConnectionInfo, List[str]]``, so both bind to one ``ConnectionInfo`` and differ only in
``sync_direction`` — which is precisely what ``SyncDirection`` is for. For the scenario-3
TransferUnit that is 4 parameters, 4 bindings, 6 connectors, 6 topics.

``aiomqtt`` is an optional extra of ``aas_middleware`` (its ``industrial`` group), so the
connector class is imported lazily. Importing this module must not require a working MQTT
stack — the registry has to exist for every flavour, including one that wires nothing
(ADR 0028), and an inspector with no ``aiomqtt`` installed must still get the projection.
"""

from __future__ import annotations

import json
import logging
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple

from aas_middleware.middleware.sync.synced_connector import SyncDirection
from graph_db_interface import IRI

from kapps_semantic_middleware.connectors.semantic import (
    ParameterBinding,
    Registration,
    semantic_connector,
)
from kapps_semantic_middleware.vocabulary import INF

logger = logging.getLogger(__name__)


try:
    from aas_middleware.connect.connectors.mqtt_client_connector import (
        MqttClientConnector,
    )
except ImportError:  # pragma: no cover - depends on the optional extra being installed
    # Importing this module must not require a working MQTT stack. The registry has to exist
    # for every flavour, including one that wires nothing (ADR 0028), so an inspector on a
    # host without aiomqtt must still get recognition and the projection. The failure is
    # deferred to the moment something actually tries to build a connector.
    MqttClientConnector = None  # type: ignore[assignment]


def _mqtt_client_connector_cls():
    """The framework connector class, or an actionable error if the extra is missing."""
    if MqttClientConnector is None:  # pragma: no cover - depends on the optional extra
        raise ImportError(
            "The MQTT semantic connector needs aiomqtt, an optional extra of "
            "aas_middleware. Install it with `uv add aiomqtt`, or construct the middleware "
            "with autoregister_connectors=False to run as an inspector."
        )
    return MqttClientConnector


class MQTTParameterFormatter:
    """Translates between an MQTT payload and the persistence value of a parameter node.

    The persistence value of a COMPLEX property is a **list of one** generated model, not a
    scalar: ``[AnonymousClass(hasValue=[12.1], hasUnit=['m/s'], accessMode=['readwrite'])]``.
    ``ConnectionInfo`` bottoms out at that property — ``field_id`` is a plain ``getattr`` and
    the node's ``inf:hasValue`` is one level further down — so the formatter is what bridges
    the device's scalar and the node the middleware persists (ADR 0023).

    **Payload shape.** Raw scalar by default; if the parameter declares
    ``inf:hasMQTTValuePath``, a JSON envelope with the value at that dotted path. The path is
    one property and is honoured symmetrically on both read and write (ADR 0023).

    **Symmetry.** ``MqttClientConnector`` is asymmetric: its listener runs
    ``json.loads(payload)`` on everything it receives, while ``consume()`` publishes its
    argument raw. So ``deserialize`` is handed an already-parsed value and ``serialize`` must
    produce the encoded bytes itself.

    **Why the node is reassembled rather than replaced by a bare value.**
    ``update_persistence_with_value`` does ``setattr(contained_model, field_id, value)``,
    replacing the whole list, and ``Formatter.deserialize`` sees only the payload — it has no
    access to the current persistence value. A bare scalar would therefore blank the unit and
    the access mode *in the model being served over REST*. ADR 0027 removed the other half of
    this problem, the graph one: a skolemised parameter node is addressable, so a commit
    diffs per triple and an unchanged facet cannot be wiped. The in-memory half remains, and
    it is what this reassembly is for — the northbound payload keeps its unit after the first
    device message. The facets come from the same metadata the binding already read, so this
    is a pure function per message with no read of current state.
    """

    def __init__(
        self,
        model_type: type,
        northbound_facets: Dict[str, Any],
        value_field: str,
        value_path: Optional[str] = None,
    ) -> None:
        self.model_type = model_type
        self.northbound_facets = northbound_facets
        self.value_field = value_field
        self.value_path = value_path

    def deserialize(self, data: Any) -> List[Any]:
        """Device payload -> the persistence value (a one-element list holding the node)."""
        value = self._extract(data)
        fields = dict(self.northbound_facets)
        fields[self.value_field] = [] if value is None else [value]
        return [self.model_type(**fields)]

    def serialize(self, data: Any) -> bytes:
        """Persistence value -> the device payload, encoded for ``consume``."""
        value = self._value_of(data)
        if self.value_path is None:
            return json.dumps(value).encode()
        envelope: Dict[str, Any] = {}
        cursor = envelope
        *branches, leaf = self.value_path.split(".")
        for part in branches:
            cursor = cursor.setdefault(part, {})
        cursor[leaf] = value
        return json.dumps(envelope).encode()

    def _extract(self, data: Any) -> Any:
        """Pull the scalar out of an inbound payload, honouring the envelope path."""
        if self.value_path is None:
            return data
        cursor = data
        for part in self.value_path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                logger.warning(
                    "MQTT payload has no %r at value path %r; treating it as unobserved",
                    part,
                    self.value_path,
                )
                return None
            cursor = cursor[part]
        return cursor

    def _value_of(self, data: Any) -> Any:
        """Pull the scalar out of a persistence value, whatever depth it arrives at.

        Accepts the one-element list the framework holds, a bare node, or an already-plain
        scalar, because an outbound value can reach here from a PUT route as easily as from
        the persistence model.
        """
        if isinstance(data, (list, tuple)):
            if not data:
                return None
            data = data[0]
        node_value = getattr(data, self.value_field, None)
        if node_value is None and isinstance(data, dict):
            node_value = data.get(self.value_field)
        if node_value is None:
            return data
        if isinstance(node_value, (list, tuple)):
            return node_value[0] if node_value else None
        return node_value


@semantic_connector
class MQTTBinding:
    """Binds an MQTT-reachable parameter to one or two ``MqttClientConnector`` instances."""

    connector_cls: ClassVar[Any] = MqttClientConnector
    interface_property: ClassVar[IRI] = INF.isInterfaceAccessibleMQTTParameter
    connection_metadata: ClassVar[Tuple[IRI, ...]] = (
        INF.hasMQTTTopic,
        INF.hasMQTTBrokerIP,
        INF.hasMQTTSetTopic,
        INF.hasMQTTValuePath,
    )

    @staticmethod
    def build(
        binding: ParameterBinding, direction: SyncDirection
    ) -> Iterable[Registration]:
        """One read registration always; one write registration when both sides permit it.

        ``direction`` has already been reduced to the most restrictive of the parameter's
        ``inf:accessMode`` and the instance's flavour (ADR 0023), so this only has to honour
        it — it must never re-widen.
        """
        connector_cls = _mqtt_client_connector_cls()

        broker = binding.get(INF.hasMQTTBrokerIP)
        topic = binding.get(INF.hasMQTTTopic)
        set_topic = binding.get(INF.hasMQTTSetTopic)
        value_path = binding.get(INF.hasMQTTValuePath)

        if not broker or not topic:
            # A parameter marked MQTT-accessible whose metadata is incomplete would come up
            # silently dead: no listener, no value, and nothing to say why. Name the property
            # and what is missing (ADR 0023).
            logger.warning(
                "Not binding %s on %s over MQTT: missing %s. The parameter will be served "
                "but no value will flow.",
                binding.parameter_property,
                binding.resource_iri,
                " and ".join(
                    name
                    for name, present in (("a broker", broker), ("a topic", topic))
                    if not present
                ),
            )
            return

        formatter = _formatter_for(binding, value_path)

        yield Registration(
            connector=connector_cls(broker, topic),
            sync_direction=SyncDirection.TO_PERSISTENCE,
            model_type=list,
            formatter=formatter,
            suffix="read",
        )

        if direction is not SyncDirection.BIDIRECTIONAL:
            return

        if not set_topic:
            logger.warning(
                "%s on %s is readwrite but declares no %s; serving it read-only.",
                binding.parameter_property,
                binding.resource_iri,
                INF.hasMQTTSetTopic,
            )
            return

        yield Registration(
            connector=connector_cls(broker, set_topic),
            sync_direction=SyncDirection.FROM_PERSISTENCE,
            model_type=list,
            formatter=formatter,
            suffix="write",
        )


def _formatter_for(
    binding: ParameterBinding, value_path: Optional[str]
) -> MQTTParameterFormatter:
    """Build the formatter for one parameter from its already-resolved northbound facets.

    The facets are the parameter node's properties minus the connection metadata — exactly the
    northbound projection of the node (ADR 0028), reached here from the binding side rather
    than from the spec side.
    """
    southbound = {str(prop) for prop in MQTTBinding.connection_metadata}
    value_field = INF.hasValue.lined
    facets = {
        IRI(prop).lined: value
        for prop, value in binding.metadata.items()
        if prop not in southbound and IRI(prop).lined != value_field
    }
    return MQTTParameterFormatter(
        model_type=binding.node_model_type,
        northbound_facets=facets,
        value_field=value_field,
        value_path=value_path,
    )
