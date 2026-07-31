# The MQTT client connector is ours, and the broker address gains a port

`kapps_semantic_middleware` writes its own MQTT client connector. `mqtt_binding.py` points
`_mqtt_client_connector_cls()` at the local class instead of at
`aas_middleware.connect.connectors.mqtt_client_connector.MqttClientConnector`.

`inf:hasMQTTBrokerPort` joins the INF interface vocabulary. An absent port means 1883, so every
ABox that exists today keeps its meaning.

## Why the port

The factory needs a broker that a launcher can put on a free port. ADR 0029 allocates every
other port that way, because the process that binds a port is the process that picks it.

The ABox cannot say so today. `mqtt_binding.py:257` calls `connector_cls(broker, topic)`.
`MqttClientConnector.__init__` declares `port: int = 1883` and nothing overrides it. A broker on
any other port is unreachable, whatever the graph says.

## Why our own class, and not a change to the sibling

Root ADR 0001 permits only a bugfix in a sibling repository. A port argument that the caller can
set is a feature, so that route is closed.

ADR 0023 already opened the right one. A semantic connector names a `connector_cls` and is not
itself a framework connector. The seam exists so that a domain expert can bring a connector we
neither own nor subclass. We are now the first user of our own seam, which is a good sign about
its shape.

The class is small. It satisfies the `Provider` and `Consumer` protocols with five methods:
`connect`, `disconnect`, `provide`, `consume` and `receive`. `mqtt_binding.py` touches it in one
place.

## Why the port is an INF term

`inf:hasMQTTBrokerIP`, `inf:hasMQTTTopic`, `inf:hasMQTTSetTopic` and `inf:hasMQTTValuePath` are
INF interface terms. A broker port is the same kind of fact, so it belongs beside them and not
in a demo-local namespace.

The consolidated INF artifact does not exist yet. #39 produces it. Until then the `inf:`
declarations live inline in `examples/transferunit.ttl`. The new property goes there with its
siblings. #39 carries it into the consolidated ontology, and #61 fetches it with the rest.

We rejected two alternatives:

- **`host:port` inside `inf:hasMQTTBrokerIP`.** No new term, and the property name then lies
  about its content. Every reader of the ABox pays for that.
- **There is no port in the ABox.** The launcher then always uses 1883, and two factories cannot share a
  host.

## What does not change

**The northbound projection needs no edit.** ADR 0028 derives the delete set from the ontology,
per parameter, at every startup. The new property is a restriction on the range of
`inf:isInterfaceAccessibleMQTTParameter`, so the projection prunes it with the other protocol
markers. A broker port cannot reach a REST route.

The term still enters through `vocabulary.py`, per ADR 0021.

## Two tickets, in this order

**This work is minimal, in milestone 1.** The local class copies the behavior that runs today and adds the
port. One client per topic, exactly as now: 4 parameters, 6 connectors and 6 topics for one
TransferUnit.

**This is a scope extension, filed as future work.** There is one client per middleware instance per broker.
Payload symmetry moves into the connector, because the framework class runs `json.loads` on
every inbound message and publishes raw. `MQTTParameterFormatter` covers that asymmetry today.

Etienne split it that way on purpose. His reason: *"we need some working running example to
refine code."* A factory of two units opens 14 MQTT connections. A local broker carries that
without complaint.

## Consequences

- `aiomqtt` becomes a direct dependency of this package. It is an optional extra of
  `aas_middleware` today, and `mqtt_binding.py` imports the connector class lazily for that
  reason. The lazy import and its actionable error message stay. An inspector instance must
  still start with no MQTT stack installed (ADR 0028).
- ADR 0023's MQTT contract gains one property. The rest of that contract stands.
- `MqttClientConnector` in the sibling repository stays untouched.

We decided on wayfinder ticket #60, under map #57.
