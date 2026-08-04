# The broker address gains a port

> **Retitled and half-retracted 2026-08-03, ticket #69.** This record was called *"The MQTT client
> connector is ours, and the broker address gains a port"*. Its first clause rested on a factual
> error and is withdrawn — see **Amendment, 2026-08-03** at the end. The port half stands, and it is
> what the record is now about. Nothing that cites ADR 0031 for the port needs to change.

`inf:hasMQTTBrokerPort` joins the INF interface vocabulary. An absent port means 1883, so every
ABox that exists today keeps its meaning.

The port is declared `xsd:integer`. A port is a number, and this is the same objection that killed
`host:port` inside `inf:hasMQTTBrokerIP` below: a property that lies about the kind of thing it
holds makes every reader of the ABox pay. `MqttClientConnector` takes an `int`, so nothing coerces
on the way in.

## Why the port

The factory needs a broker that a launcher can put on a free port. ADR 0029 allocates every
other port that way, because the process that binds a port is the process that picks it.

The ABox cannot say so today. `mqtt_binding.py:257` calls `connector_cls(broker, topic)`.
`MqttClientConnector.__init__` declares `port: int = 1883` and nothing overrides it. A broker on
any other port is unreachable, whatever the graph says.

## Why our own class, and not a change to the sibling

> **Retracted 2026-08-03, ticket #69.** The premise below is false. No local class is written, and
> no sibling change was ever needed. Kept because the reasoning is sound given the premise, and
> because the amendment at the end is only legible next to it.

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

- ~~`aiomqtt` becomes a direct dependency of this package.~~ It already is one
  (`pyproject.toml`, since #40). The lazy import in `mqtt_binding.py` and its actionable error
  message stay regardless, because an inspector instance must still start with no MQTT stack
  installed (ADR 0028).
- ADR 0023's MQTT contract gains one property. The rest of that contract stands.
- `MqttClientConnector` in the sibling repository stays untouched.

We decided on wayfinder ticket #60, under map #57.

## Amendment, 2026-08-03, ticket #69 — no local class, because the sibling already takes a port

**The premise was wrong.** This record argued that a settable port is a *feature*, that root
ADR 0001 therefore closes the sibling route, and that we must write our own class. The sibling
class already has it:

```python
# aas_middleware/connect/connectors/mqtt_client_connector.py
def __init__(self, broker_ip: str, topic: str, port: int = 1883):
```

`port` is a public constructor argument today. `mqtt_binding.py` simply never passed it. Root
ADR 0001 was never engaged, because nothing in the sibling has to change. This record even states
the fact correctly — *"declares `port: int = 1883` and nothing overrides it"* — and then draws the
opposite conclusion from it. Read "nothing overrides it" as a defect in our call site, which is
what it was.

**So `MQTTBinding.build` calls `connector_cls(broker, topic, port)` and that is the whole change.**
`_mqtt_client_connector_cls()` keeps returning the framework class. Roughly ninety lines of copied
retry, listener-task and reconnect logic are not written — logic we would then have had to carry
the sibling's fixes into by hand, and the sibling repaired `disconnect()` three commits ago.

**The local class is not abandoned, it is relocated.** It moves to *MQTT connector scope extension:
one client per instance per broker, and payload symmetry* (#70), where it is genuinely forced:
`MqttClientConnector` takes a single topic and cannot multiplex, and its `receive` runs
`json.loads` while its `consume` publishes raw. Those need our own class. A port never did.

**The general lesson, and it is the reason this is an amendment rather than a deletion.** This
record reasoned from a policy (root ADR 0001) to a conclusion about a dependency without reading
the dependency. Read the sibling's source before concluding that a sibling change is needed.

## Amendment, 2026-08-03, ticket #69 — the port alone is not enough to reach a broker

A declared port says *where* a broker is. It does not make one exist. ADR 0029 as amended gives
each TransferUnit its own broker, so something has to bring one up, and this record's original
framing — the launcher puts a broker on a free port — no longer holds.

**ADR 0034 records the seam that does it**: the binding, on registering its first connector for a
declared address, asks its caller to ensure transport exists there. This record and ADR 0034 are
two halves of one mechanism. The ABox can say which broker (here), and the middleware can bring
that broker up (ADR 0034).
