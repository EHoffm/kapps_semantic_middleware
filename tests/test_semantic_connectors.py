"""Unit tests for the semantic-connector seam (#40, ADR 0023 / ADR 0028).

Pure logic — no GraphDB, no broker, no network. The seam exists precisely so that a binding
can be described and reasoned about without a running middleware, and these tests are the
first consumer of that property.
"""

from __future__ import annotations

import logging

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
from kapps_semantic_middleware.projection import (
    ProjectionError,
    carries_southbound,
    cross_check,
    prune_southbound,
)
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
    """Resolution is by interface property; the registry knows what each binding reads."""

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
        assert str(IRI(f"{OTHER_NS}hasStubEndpoint")) in registry.declared_connection_metadata()

    def test_declared_metadata_is_the_union_of_every_binding(self):
        registry = SemanticConnectorRegistry([MQTTBinding])
        assert registry.declared_connection_metadata() == {
            str(INF.hasMQTTTopic),
            str(INF.hasMQTTBrokerIP),
            str(INF.hasMQTTSetTopic),
            str(INF.hasMQTTValuePath),
        }

    def test_no_binding_declares_hasvalue_or_accessmode(self):
        """Northbound-safe content must survive the projection, or the view is useless."""
        southbound = SemanticConnectorRegistry([MQTTBinding]).declared_connection_metadata()
        assert str(INF.hasValue) not in southbound
        assert str(INF.accessMode) not in southbound


class TestDefaultRegistry:
    """The default registry must be populated by import alone.

    A middleware constructed without an explicit ``connector_registry`` gets the default one.
    If nothing imported the binding modules, no protocol is recognised, so nothing is wired
    and every parameter comes up dead. Every test that builds
    ``SemanticConnectorRegistry([MQTTBinding])`` explicitly is structurally blind to this,
    which is exactly how it went unnoticed.

    Note the *projection* no longer depends on this being populated — it asks the ontology
    (ADR 0028) — so an empty registry is now a wiring failure rather than a leak.
    """

    def test_importing_the_package_registers_the_builtin_bindings(self):
        from kapps_semantic_middleware.connectors.semantic import default_registry

        assert len(default_registry) >= 1

    def test_the_default_registry_declares_the_mqtt_metadata(self):
        from kapps_semantic_middleware.connectors.semantic import default_registry

        southbound = default_registry.declared_connection_metadata()

        assert {
            str(INF.hasMQTTTopic),
            str(INF.hasMQTTSetTopic),
            str(INF.hasMQTTBrokerIP),
            str(INF.hasMQTTValuePath),
        } <= southbound

    def test_mqtt_is_reachable_through_the_default_registry(self):
        from kapps_semantic_middleware.connectors.semantic import default_registry

        assert (
            default_registry.for_interface_property(
                INF.isInterfaceAccessibleMQTTParameter
            )
            is MQTTBinding
        )


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
        """inf:hasMQTTValuePath is one property, honoured symmetrically (ADR 0023)."""
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


class _FakeOGM:
    """Answers the two SPARQL shapes `projection` issues, from a declared hierarchy.

    The projection reads the ontology, so a unit test has to supply one. Rather than mock the
    functions under test, this mocks the *store* — the queries stay real, and a mistake in one
    still shows up here.
    """

    def __init__(self, markers, declares):
        self.markers = markers  # parameter property -> [protocol marker, ...]
        self.declares = declares  # marker -> [property, ...]
        self.db = self

    def query(self, q, convert_bindings=False):
        if "?marker" in q and "onProperty" not in q:
            param = q.split("<", 1)[1].split(">", 1)[0]
            rows = [{"marker": m} for m in self.markers.get(param, [])]
            return {"results": {"bindings": rows}}
        wanted = [m for m in self.declares if f"<{m}>" in q]
        props = {p for m in wanted for p in self.declares[m]}
        return {"results": {"bindings": [{"p": p} for p in sorted(props)]}}


MQTT_MARKER = str(INF.isInterfaceAccessibleMQTTParameter)
OPCUA_MARKER = f"{OTHER_NS}isInterfaceAccessibleOPCUAParameter"
OPCUA_ENDPOINT = f"{OTHER_NS}hasOPCUAEndpoint"


def _ogm(*markers):
    return _FakeOGM(
        markers={str(SPEED): list(markers)},
        declares={
            MQTT_MARKER: [
                str(INF.hasMQTTTopic),
                str(INF.hasMQTTBrokerIP),
                str(INF.hasMQTTSetTopic),
            ],
            OPCUA_MARKER: [OPCUA_ENDPOINT],
        },
    )


class TestProjection:
    """The northbound view is the pruned spec, and the ontology decides what is pruned."""

    class _Spec:
        """A minimal stand-in with the two attributes the prune walks."""

        def __init__(self, properties):
            self.properties = properties

    class _Prop:
        def __init__(self, nested=None):
            self.nested = nested

    def _resource_spec(self, extra=()):
        fields = {
            INF.hasValue: self._Prop(),
            INF.accessMode: self._Prop(),
            INF.hasMQTTTopic: self._Prop(),
            INF.hasMQTTBrokerIP: self._Prop(),
            INF.hasMQTTSetTopic: self._Prop(),
        }
        for name in extra:
            fields[IRI(name)] = self._Prop()
        return self._Spec({SPEED: self._Prop(nested=self._Spec(fields))})

    def test_prune_removes_what_the_ontology_calls_protocol_metadata(self):
        pruned = prune_southbound(self._resource_spec(), ogm=_ogm(MQTT_MARKER))

        assert set(pruned.properties[SPEED].nested.properties) == {
            INF.hasValue,
            INF.accessMode,
        }

    def test_an_unregistered_protocol_is_pruned_too(self):
        """The regression this whole mechanism exists for.

        A belt reachable over MQTT *and* OPC-UA, with no OPC-UA binding registered anywhere.
        The old registry-derived prune set removed the MQTT metadata and served the OPC-UA
        endpoint, because a set built from registered code only knows the protocols we happen
        to have written. Asking the ontology finds it.
        """
        spec = self._resource_spec(extra=[OPCUA_ENDPOINT])

        pruned = prune_southbound(spec, ogm=_ogm(MQTT_MARKER, OPCUA_MARKER))

        assert set(pruned.properties[SPEED].nested.properties) == {
            INF.hasValue,
            INF.accessMode,
        }
        assert IRI(OPCUA_ENDPOINT) not in pruned.properties[SPEED].nested.properties

    def test_a_property_with_no_protocol_marker_is_untouched(self):
        """An ordinary object property is not interface-accessible and loses nothing."""
        pruned = prune_southbound(self._resource_spec(), ogm=_ogm())

        assert set(pruned.properties[SPEED].nested.properties) == {
            INF.hasValue,
            INF.accessMode,
            INF.hasMQTTTopic,
            INF.hasMQTTBrokerIP,
            INF.hasMQTTSetTopic,
        }

    def test_prune_does_not_mutate_the_input_spec(self):
        """Both shapes are needed at once: the full one wires, the pruned one serves."""
        spec = self._resource_spec()

        prune_southbound(spec, ogm=_ogm(MQTT_MARKER))

        assert INF.hasMQTTBrokerIP in spec.properties[SPEED].nested.properties

    def test_unreadable_protocol_ranges_refuse_to_serve(self):
        """A projection that cannot prove a payload safe must not serve it.

        The ontology says the parameter is reached over a protocol, but nothing can be read
        from that protocol's range — a missing TBox, or a range shape we do not understand.
        Continuing would mean serving fields we have not classified.
        """
        blind = _FakeOGM(markers={str(SPEED): [MQTT_MARKER]}, declares={})

        with pytest.raises(ProjectionError) as exc:
            prune_southbound(self._resource_spec(), ogm=blind)

        assert "cannot prove what is safe" in str(exc.value)


class TestCrossCheck:
    """The ontology governs; a binding's declaration is compared against it and reported."""

    def test_agreement_is_silent(self, caplog):
        cross_check(SPEED, [INF.hasMQTTTopic], [INF.hasMQTTTopic])

        assert not caplog.text

    def test_a_term_only_the_ontology_declares_is_reported(self, caplog):
        cross_check(SPEED, [INF.hasMQTTTopic, INF.hasMQTTValuePath], [INF.hasMQTTTopic])

        assert "hasMQTTValuePath" in caplog.text

    def test_a_term_only_the_binding_declares_is_reported(self, caplog):
        """The direction that costs debugging time: it will not survive a write."""
        cross_check(SPEED, [INF.hasMQTTTopic], [INF.hasMQTTTopic, INF.hasMQTTSetTopic])

        assert "hasMQTTSetTopic" in caplog.text
        assert "may come up with no value flowing" in caplog.text

    def test_a_binding_that_declares_nothing_is_not_cross_checked(self, caplog):
        cross_check(SPEED, [INF.hasMQTTTopic], None)

        assert not caplog.text


class TestLeakDetector:
    def test_carries_southbound_detects_a_raw_iri(self):
        southbound = SemanticConnectorRegistry([MQTTBinding]).declared_connection_metadata()
        payload = {str(INF.hasMQTTBrokerIP): ["127.0.0.1"]}

        assert carries_southbound(payload, southbound) == {str(INF.hasMQTTBrokerIP)}

    def test_carries_southbound_detects_a_mangled_field_name(self):
        """A served JSON body carries IRI-mangled field names, not raw IRIs."""
        southbound = SemanticConnectorRegistry([MQTTBinding]).declared_connection_metadata()
        payload = {INF.hasMQTTBrokerIP.lined: ["127.0.0.1"]}

        assert carries_southbound(payload, southbound) == {str(INF.hasMQTTBrokerIP)}

    def test_a_clean_payload_carries_nothing(self):
        southbound = SemanticConnectorRegistry([MQTTBinding]).declared_connection_metadata()
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


class TestActivityLogging:
    """Inbound logs at INFO only on change; outbound logs every setpoint.

    This keeps the activity feed readable: the mock PLC republishes every value
    every 0.2 s across four topics, so logging each arrival at INFO buries the feed
    in seconds. Measured on a live run, this suppresses 97.9 % of arrivals — 240
    messages became 5 INFO lines.
    """

    def _formatter(self, caplog):
        """Build a formatter with caplog configured for the binding logger."""
        caplog.set_level(logging.DEBUG, logger="kapps_semantic_middleware.connectors.mqtt_binding")

        model = _node_model()
        return MQTTParameterFormatter(
            model_type=model,
            northbound_facets={
                INF.accessMode.lined: ["readwrite"],
                IRI("https://example.org/tu#hasUnit").lined: ["m/s"],
            },
            value_field=INF.hasValue.lined,
            value_path=None,
            parameter_label="Belt1 hasConveyorSpeed",
            topic="belt/speed",
            set_topic="belt/speed_set",
        )

    def test_a_changed_inbound_value_logs_at_info(self, caplog):
        """A changed value is news and must appear at INFO."""
        formatter = self._formatter(caplog)

        formatter.deserialize(1.5)
        formatter.deserialize(2.5)

        records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(records) == 2
        assert all("belt/speed" in r.message for r in records)

    def test_a_repeated_inbound_value_drops_to_debug(self, caplog):
        """A periodic republish of an unchanged value is noise; a change is news.

        Without this split the feed is unreadable within seconds.
        """
        formatter = self._formatter(caplog)

        formatter.deserialize(1.5)
        formatter.deserialize(1.5)

        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]

        assert len(info_records) == 1
        assert len(debug_records) == 1
        assert "belt/speed" in info_records[0].message

    def test_the_first_value_is_always_news_even_if_it_is_none(self, caplog):
        """The _UNSET sentinel ensures the first reading logs even when None.

        Initialising last value to None instead would silently swallow the first
        reading of a parameter that legitimately starts unobserved.
        """
        formatter = self._formatter(caplog)

        formatter.deserialize(None)

        records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(records) == 1
        assert "belt/speed" in records[0].message

    def test_an_outbound_setpoint_always_logs_at_info(self, caplog):
        """Outbound logs at INFO every time; the asymmetry with inbound is deliberate.

        A setpoint is always news — something chose to act — so no change-detection
        applies here.
        """
        formatter = self._formatter(caplog)
        # Building a node to send costs one inbound line; drop it so the count below is
        # about the setpoints alone rather than about how the fixture got its value.
        [node] = formatter.deserialize(3.5)
        caplog.clear()

        formatter.serialize([node])
        formatter.serialize([node])

        records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(records) == 2
        assert all("belt/speed_set" in r.message for r in records)
