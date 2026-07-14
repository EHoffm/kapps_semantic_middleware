# Wrap OGM access as an aas_middleware Connector

Knowledge graph reads/writes (`kapps_ogm.OGM.fetch`/`commit`) are wrapped in a
`KnowledgeGraphConnector` implementing `aas_middleware`'s `Connector` protocol
(`connect`/`disconnect`/`provide`/`consume`) rather than being called directly and
separately by every piece of registration/execution logic that needs the graph.

**Why**: the paper names this pattern explicitly — "synchronization with the knowledge graph
is itself a connector in this framework: an upstream connector wraps the OGM's operations and
persists changes through explicit commit calls... mirroring the transaction patterns of
conventional manufacturing execution systems." Wrapping OGM access this way, rather than
calling `ogm.fetch`/`ogm.commit` ad hoc from workflow/state registration code, means
`kapps_semantic_middleware`'s own internal graph access goes through the same connector
abstraction as OT devices (MQTT/OPC UA/HTTP), and any future MES-style synchronization
pattern (`SyncedConnector`, `SyncRole`/`SyncDirection`) that `aas_middleware` already
provides for other connectors becomes available for knowledge-graph synchronization too,
without new plumbing.

**Consequence**: this also becomes the extension point for `@state`'s value source — a
StateProperty's getter can be backed by *any* `aas_middleware` connector (an `OpcUaConnector`
reading a PLC register, an `MqttClientConnector` subscribed to a topic), not just an
arbitrary Python function, reusing the existing IT/OT bridge directly instead of requiring
every device integration to hand-roll its own polling loop.
