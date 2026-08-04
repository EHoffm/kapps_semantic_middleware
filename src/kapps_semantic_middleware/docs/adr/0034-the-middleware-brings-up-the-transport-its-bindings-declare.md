# The middleware brings up the transport its bindings declare, through a seam the deployment fills

A binding reads a broker address out of the graph. Before it builds the first connector for that
address, it calls a hook the middleware was constructed with:

```python
SemanticMiddleware(..., ensure_transport=my_starter)

# called once per distinct declared address, during construction
def my_starter(host: str, port: int) -> None: ...
```

The library never starts a broker, never probes one, never stops one, and never reads a return
value. It states a need. Whoever built the deployment decides how that need is met.

An instance constructed without `ensure_transport` behaves exactly as it does today. Scenarios 1
and 2, the five frozen scenario-3 test files, and any consumer of this library are unaffected.

## Why there is a hook at all

The TransferUnit Expert's job is supposed to be self-contained (ADR 0033): they configure a
middleware for their product, it reads the unit out of the graph, wires its connectors, serves its
datamodel and publishes its address — and they are finished. ADR 0029 as amended found the hole in
that story. The expert still had to depend on somebody else having arranged transport. A middleware
that brings up the transport its own bindings declare closes it.

Etienne set the rule on 2026-08-03: *"every transferunit instance in the demo gets its own mqtt
broker, that gets initiated on the first time a mqttconnector gets registered. For every attribute
that will get a connector after that, the middlewares then existing broker serves as a broker."*

## Why the library does not start the broker itself

Root ADR 0004 as amended lets a **protocol mechanism the middleware itself defines** into `src/`. A
third-party MQTT broker is not that. It is transport infrastructure the middleware consumes.

Putting `amqtt` inside `mqtt_binding.py` would have made a broker a runtime dependency of the
library, and would have shipped a strong opinion by default: every consumer that registers an MQTT
connector gets a broker started underneath it, including one deployed against a real factory broker
that happens to be briefly unreachable. The demo needs that behaviour. A library does not get to
assume everyone does.

Doing it in the demo's unit runner instead was the other candidate. It is the cheapest thing that
works, and it was rejected because it is *eager*: it would start a broker whether or not any
parameter asked for MQTT, and it would re-derive the port from a formula rather than use the address
the graph actually declared. The point of this middleware is that the graph is the contract. A
runner that computes what the graph already states weakens that in the one place the demo exists to
demonstrate it.

The hook keeps all three properties: registration-driven, graph-derived, and free of any transport
implementation in `src/`.

## Why "ensure", and why once per address

**The library does not probe.** A socket connect with a timeout inside the middleware constructor
would give the library an opinion about how broker liveness is tested, and a filtered or slow host
would stall construction before the app is built. The contract is one sentence — *ensure something
is listening at this address* — and the callback owns probing, starting, and lifetime. It must be
idempotent.

**Once per distinct `(host, port)`, not once per instance.** Etienne's sentence — the then-existing
broker serves the later attributes — is a true description of the demo, where all four of a unit's
parameters declare the same address, so the hook fires exactly once and later connectors find the
broker standing. Keying on the address gets that for free without the library having to *assume*
it. A resource whose parameters ever named two brokers gets two, and nothing lies. The literal
reading — call once, first address wins — was rejected for that case: the second broker would
silently not exist, and a connector dialling a dead port looks like a network fault rather than a
configuration one.

**The library owns no lifetime.** It never stops what the callback started. In the demo the
callback runs an in-process `amqtt` broker on a daemon thread, so it dies with the middleware
process — which is what ADR 0029's amendment means by *a unit's broker dies with its unit*, with no
teardown code and no orphan risk.

## Where it fires

`MQTTBinding.build` is reached from `plan_wiring`, which runs in the middleware **constructor**
(ADR 0023: bindings register at construction, or inbound traffic dies silently). So the hook is a
plain synchronous callback. It cannot be `async`, and it runs before any event loop exists.

That is also why the broker cannot simply be started on the middleware's own loop: the framework's
`lifespan` calls `connector.connect()` as its very first act, and by then a connector that dialled a
non-existent broker has already begun its retry.

## Consequences

- `SemanticMiddleware` gains one optional constructor argument. It is the only public surface this
  adds, and its default preserves every existing behaviour.
- The seam is protocol-agnostic by shape. ADR 0033's REST binding has nothing to bring up, so it
  never calls it; a future protocol that does gets it for nothing.
- **The demo teaches the library back.** Etienne, 2026-08-03: *"we go library, then demo, and we
  learn from building the demo to reflect back into the library."* Root ADR 0004's promotion rule
  runs from `demo/` into `src/`; this is the same loop in the other direction — a seam shipped in
  `src/` on one caller's evidence, whose shape is provisional until the demo has actually used it.
  Revisit the argument's name, its signature and its once-per-address rule after the factory runs.
- ADR 0031 and this record are two halves of one mechanism: the ABox can say which broker, and the
  middleware can bring that broker up.

Decided on wayfinder ticket #69, under map #57.
