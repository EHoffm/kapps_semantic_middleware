"""Unit tests for the semantic-connector seam (#40, ADR 0023 / ADR 0028).

Pure logic — no GraphDB, no broker, no network. The seam exists precisely so that a binding
can be described and reasoned about without a running middleware, and these tests are the
first consumer of that property.
"""

from __future__ import annotations

import json

import pytest
from aas_middleware.middleware.sync.synced_connector import SyncDirection
from graph_db_interface import IRI
from pydantic import BaseModel

from kapps_semantic_middleware.connectors.mqtt_binding import (
    MQTTBinding,
    MQTTParameterFormatter,
)
from kapps_semantic_middleware.connectors.semantic import (
    ParameterBinding,
    Registration,
    SemanticConnectorRegistry,
    normalize_metadata,
    resolve_direction,
)
from kapps_semantic_middleware.projection import carries_southbound, prune_southbound
from kapps_semantic_middleware.vocabulary import INF, AccessMode

BELT = IRI("https://example.org/tu#Belt1")
SPEED = IRI("https://example.org/tu#hasConveyorSpeed")
OTHER_NS = "https://example.org/other#"


class _NodeModel(BaseModel):
    """Stands in for the AnonymousClass the OGM generates for a parameter node."""

    model_config = {"extra": "forbid"}


def _node_model():
    """A node model with the field names the OGM would mangle out of the inf: IRIs."""
    fields = {
        INF.hasValue.lined: (list, []),
        INF.accessMode.lined: (list, []),
        IRI("https://example.org/tu#hasUnit").lined: (list, []),
    }
    from pydantic import create_model

    return create_model("AnonymousClass", **{k: (v[0], v[1]) for k, v in fields.items()})


def _binding(access_mode=AccessMode.READWRITE, value_path=None, set_topic="belt/speed_set"):
    metadata = {
        str(INF.accessMode): [access_mode],
        str(IRI("https://example.org/tu#hasUnit")): ["m/s"],
        str(INF.hasMQTTTopic): ["belt/speed"],
        str(INF.hasMQTTBrokerIP): ["127.0.0.1"],
    }
    if set_topic is not None:
        metadata[str(INF.hasMQTTSetTopic)] = [set_topic]
    if value_path is not None:
        metadata[str(INF.hasMQTTValuePath)] = [value_path]
    return ParameterBinding(
        resource_iri=BELT,
        parameter_property=SPEED,
        field_id=SPEED.lined,
        metadata=normalize_metadata(metadata),
        descriptor=MQTTBinding,
        node_model_type=_node_model(),
    )


class TestRegistry:
    """Resolution is by interface property, and the registry knows the prune set."""

    def test_resolves_a_registered_descriptor(self):
        registry = SemanticConnectorRegistry([MQTTBinding])
        assert (
            registry.for_interface_property(INF.isInterfaceAccessibleMQTTParameter)
            is MQTTBinding
        )

    def test_unregistered_interface_property_resolves_to_nothing(self):
        registry = SemanticConnectorRegistry([MQTTBinding])
        assert registry.for_interface_property(IRI(f"{OTHER_NS}isSomethingElse")) is None

    def test_a_second_interface_class_registers_without_touching_core(self):
        """#40's acceptance: a stub protocol registers alongside MQTT, no core change."""

        class StubBinding:
            connector_cls = object
            interface_property = IRI(f"{OTHER_NS}isInterfaceAccessibleStubParameter")
            connection_metadata = (IRI(f"{OTHER_NS}hasStubEndpoint"),)

            @staticmethod
            def build(binding, direction):
                return ()

        registry = SemanticConnectorRegistry([MQTTBinding, StubBinding])

        assert len(registry) == 2
        assert registry.for_interface_property(StubBinding.interface_property) is StubBinding
        # And the newcomer's terms are projected out for free (ADR 0028).
        assert str(IRI(f"{OTHER_NS}hasStubEndpoint")) in registry.southbound_properties()

    def test_southbound_set_is_the_union_of_every_binding(self):
        registry = SemanticConnectorRegistry([MQTTBinding])
        assert registry.southbound_properties() == {
            str(INF.hasMQTTTopic),
            str(INF.hasMQTTBrokerIP),
            str(INF.hasMQTTSetTopic),
            str(INF.hasMQTTValuePath),
        }

    def test_hasvalue_and_accessmode_are_never_southbound(self):
        """Northbound-safe content must survive the projection, or the view is useless."""
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()
        assert str(INF.hasValue) not in southbound
        assert str(INF.accessMode) not in southbound


class TestDirection:
    """Direction is the most restrictive of accessMode x flavour; neither may widen."""

    @pytest.mark.parametrize(
        "access_mode, flavour, expected",
        [
            # A controller may drive a settable parameter -- the only writable combination.
            (AccessMode.READWRITE, SyncDirection.BIDIRECTIONAL, SyncDirection.BIDIRECTIONAL),
            # A monitor cannot drive even a settable one.
            (AccessMode.READWRITE, SyncDirection.TO_PERSISTENCE, SyncDirection.TO_PERSISTENCE),
            # A controller cannot write a read-only sensor.
            (AccessMode.READ, SyncDirection.BIDIRECTIONAL, SyncDirection.TO_PERSISTENCE),
            (AccessMode.READ, SyncDirection.TO_PERSISTENCE, SyncDirection.TO_PERSISTENCE),
        ],
    )
    def test_most_restrictive_wins(self, access_mode, flavour, expected):
        assert resolve_direction(access_mode, flavour) is expected

    def test_absent_access_mode_is_read_only(self):
        """A parameter is never writable by accident of omission (ADR 0023)."""
        binding = ParameterBinding(
            resource_iri=BELT,
            parameter_property=SPEED,
            field_id=SPEED.lined,
            metadata={},
            descriptor=MQTTBinding,
            node_model_type=_node_model(),
        )
        assert binding.access_mode == AccessMode.READ
        assert (
            resolve_direction(binding.access_mode, SyncDirection.BIDIRECTIONAL)
            is SyncDirection.TO_PERSISTENCE
        )

    def test_unrecognised_access_mode_is_read_only(self):
        binding = _binding(access_mode="write-whenever-you-like")
        assert binding.access_mode == AccessMode.READ


class TestMQTTBindingBuild:
    """4 parameters -> 4 bindings -> 6 connectors: a settable parameter needs two."""

    def test_settable_parameter_yields_read_and_write_registrations(self):
        registrations = list(MQTTBinding.build(_binding(), SyncDirection.BIDIRECTIONAL))

        assert [r.sync_direction for r in registrations] == [
            SyncDirection.TO_PERSISTENCE,
            SyncDirection.FROM_PERSISTENCE,
        ]
        assert [r.connector.topic for r in registrations] == [
            "belt/speed",
            "belt/speed_set",
        ]
        # Both legs share one broker, and one ConnectionInfo will bind them (ADR 0023).
        assert {r.connector.mqtt_broker_ip for r in registrations} == {"127.0.0.1"}

    def test_read_only_direction_yields_only_the_read_leg(self):
        registrations = list(MQTTBinding.build(_binding(), SyncDirection.TO_PERSISTENCE))

        assert len(registrations) == 1
        assert registrations[0].sync_direction is SyncDirection.TO_PERSISTENCE
        assert registrations[0].connector.topic == "belt/speed"

    def test_readwrite_without_a_set_topic_degrades_to_read_only(self, caplog):
        """The connector publishes where it subscribes, so no set topic means no write leg."""
        registrations = list(
            MQTTBinding.build(_binding(set_topic=None), SyncDirection.BIDIRECTIONAL)
        )

        assert len(registrations) == 1
        assert "readwrite but declares no" in caplog.text

    def test_missing_broker_binds_nothing_and_says_why(self, caplog):
        """A silently dead parameter is the failure mode this warning exists to prevent."""
        binding = _binding()
        binding.metadata.pop(str(INF.hasMQTTBrokerIP))

        assert list(MQTTBinding.build(binding, SyncDirection.BIDIRECTIONAL)) == []
        assert "missing a broker" in caplog.text
        assert str(SPEED) in caplog.text


class TestMQTTFormatter:
    """The formatter bridges a device scalar and the one-element list the framework holds."""

    def _formatter(self, value_path=None):
        model = _node_model()
        return MQTTParameterFormatter(
            model_type=model,
            northbound_facets={
                INF.accessMode.lined: ["readwrite"],
                IRI("https://example.org/tu#hasUnit").lined: ["m/s"],
            },
            value_field=INF.hasValue.lined,
            value_path=value_path,
        )

    def test_deserialize_wraps_a_scalar_into_the_node(self):
        [node] = self._formatter().deserialize(12.1)

        assert getattr(node, INF.hasValue.lined) == [12.1]

    def test_deserialize_preserves_the_static_facets(self):
        """setattr replaces the whole list, so a bare value would blank the unit in the
        model that is served over REST (ADR 0023; the graph half is ADR 0027)."""
        [node] = self._formatter().deserialize(12.1)

        assert getattr(node, IRI("https://example.org/tu#hasUnit").lined) == ["m/s"]
        assert getattr(node, INF.accessMode.lined) == ["readwrite"]

    def test_serialize_produces_a_raw_scalar_payload(self):
        """consume() publishes its argument raw, so the formatter encodes it."""
        formatter = self._formatter()
        [node] = formatter.deserialize(3.5)

        assert json.loads(formatter.serialize([node])) == 3.5

    def test_round_trips_a_scalar(self):
        formatter = self._formatter()

        assert json.loads(formatter.serialize(formatter.deserialize(7.25))) == 7.25

    def test_round_trips_a_json_envelope(self):
        """inf:hasMQTTValuePath is one property, honoured symmetrically (ADR 0016)."""
        formatter = self._formatter(value_path="payload.speed")

        [node] = formatter.deserialize({"payload": {"speed": 4.5}, "ts": 123})
        assert getattr(node, INF.hasValue.lined) == [4.5]

        assert json.loads(formatter.serialize([node])) == {"payload": {"speed": 4.5}}

    def test_envelope_missing_the_path_reads_as_unobserved(self, caplog):
        formatter = self._formatter(value_path="payload.speed")

        [node] = formatter.deserialize({"other": 1})
        assert getattr(node, INF.hasValue.lined) == []
        assert "value path" in caplog.text

    def test_an_unobserved_parameter_serializes_as_null(self):
        """Scenario 3 is a locator: a parameter has no value until the device publishes."""
        formatter = self._formatter()
        [node] = formatter.deserialize(None)

        assert json.loads(formatter.serialize([node])) is None


class TestProjection:
    """The northbound view is the pruned spec, and the prune is what makes it safe."""

    class _Spec:
        """A minimal stand-in with the two attributes prune_southbound walks."""

        def __init__(self, properties):
            self.properties = properties

    class _Prop:
        def __init__(self, nested=None):
            self.nested = nested

    def _resource_spec(self):
        node = self._Spec(
            {
                INF.hasValue: self._Prop(),
                INF.accessMode: self._Prop(),
                INF.hasMQTTTopic: self._Prop(),
                INF.hasMQTTBrokerIP: self._Prop(),
                INF.hasMQTTSetTopic: self._Prop(),
            }
        )
        return self._Spec({SPEED: self._Prop(nested=node)})

    def test_prune_removes_southbound_properties_from_the_nested_spec(self):
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()

        pruned = prune_southbound(self._resource_spec(), southbound)

        assert set(pruned.properties[SPEED].nested.properties) == {
            INF.hasValue,
            INF.accessMode,
        }

    def test_prune_does_not_mutate_the_input_spec(self):
        """Both shapes are needed at once: the full one wires, the pruned one serves."""
        spec = self._resource_spec()
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()

        prune_southbound(spec, southbound)

        assert INF.hasMQTTBrokerIP in spec.properties[SPEED].nested.properties

    def test_carries_southbound_detects_a_raw_iri(self):
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()
        payload = {str(INF.hasMQTTBrokerIP): ["127.0.0.1"]}

        assert carries_southbound(payload, southbound) == {str(INF.hasMQTTBrokerIP)}

    def test_carries_southbound_detects_a_mangled_field_name(self):
        """A served JSON body carries IRI-mangled field names, not raw IRIs."""
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()
        payload = {INF.hasMQTTBrokerIP.lined: ["127.0.0.1"]}

        assert carries_southbound(payload, southbound) == {str(INF.hasMQTTBrokerIP)}

    def test_a_clean_payload_carries_nothing(self):
        southbound = SemanticConnectorRegistry([MQTTBinding]).southbound_properties()
        payload = {INF.hasValue.lined: [12.1], INF.accessMode.lined: ["readwrite"]}

        assert carries_southbound(payload, southbound) == set()


class TestRegistrationShape:
    def test_registration_is_hashable_and_frozen(self):
        """Registrations are described, not performed, so they must be safe to pass around."""
        registration = Registration(
            connector=object(),
            sync_direction=SyncDirection.TO_PERSISTENCE,
            model_type=list,
        )
        with pytest.raises(Exception):
            registration.sync_direction = SyncDirection.BIDIRECTIONAL
