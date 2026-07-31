# The factory is one process per participant, and a launcher builds the initial situation

An N-unit factory runs as **2N+3 processes**. Per unit: one process holding the mock PLC and its
panel UI, and one holding that unit's middleware instance. Plus a controller, a monitor, and a
**launcher** that starts everything.

```
launcher            fixed port, the only bookmarkable one; seeds the graph, spawns, indexes, stops
├── plc-1           MockTransferUnit + its panel     (asyncio; no GraphDB credentials, ever)
├── middleware-1    SemanticMiddleware               (uvicorn owns the process's only loop)
├── plc-2           …
├── middleware-2    …
├── controller      SemanticMiddleware, resource-mode planner
└── monitor         SemanticMiddleware, multi-resource observer
```

Nothing is a thread of something else. A PLC really is its own box, and a middleware instance
really is a separate deployment of the library.

## Why

### One process per middleware is what makes graceful shutdown fire at all

The library's shutdown handling already exists, and it is correct. `middleware.py` registers
`_deregister_service`, `_stop_heartbeat` and `_stop_sweep` as `on_shutdown` callbacks. A
resource-mode instance then removes its own reachability and stops its loops at ASGI lifespan
shutdown.

It never ran. The serving idiom in `examples/` and `tests/` puts `uvicorn.Server.run()` on a
daemon thread. Uvicorn then declines to install signal handlers off the main thread. The reason
is verbatim from `uvicorn/server.py`:

```python
# Signals can only be listened to from the main thread.
if threading.current_thread() is not threading.main_thread():
    yield
    return
```

No handler means SIGTERM never reaches the lifespan shutdown, so none of the three callbacks fire.
Scenarios 1 and 2 leave their Service individuals in the graph on every exit. The bug is not in the
shutdown code. It is in the process shape around it. One process per middleware, with uvicorn on
the main thread, turns an existing feature on.

The same shape dissolves the deadlock behind the unserved scenario-3 walkthrough. One loop per
process means one loop for both jobs. The loop that wires the MQTT connectors also drives them.

### The launcher is scaffolding, and must stay outside the semantic world

The demo starts on an empty repository. A real factory does not: its TransferUnits are already
there, installed and registered long before any controller starts. The launcher exists purely to
manufacture that initial situation. It seeds the graph and starts the processes. It is therefore a
stand-in for reality, and not a participant in it.

A `cfc:Resource` with a provisioning `cfc:Capability` was considered, and the idea attracts. The
controller would then reach it through ADR 0002 capability resolution, with no configured endpoint
anywhere. ADR 0009 would make a spawn request durable for free. It was rejected because it asserts
something false. Provisioning a machine is not a semantic-middleware concern. Nobody dispatches an
Operation to bolt a conveyor to the floor. A launcher in the graph would teach a viewer that the
middleware does something it does not do.

The cost is accepted honestly: the launcher's own address is configuration rather than discovery. It
is the only such address in the system, and it belongs to the one component that is not part of what
is demonstrated.

### The seed is the launcher's job, because the launcher decides N

Which triples exist depends on the number of units. The seed therefore cannot run before the
launcher and hand it a fixed world. The launcher mints the unit IRIs and writes the ABox. It then
starts the processes that inhabit it. One authority holds the shape of the factory.

This also removes a split the map was worried about: seeded units and runtime-added units take the
**same** path, because there is only one path. The same code provisions a unit added ten minutes
later and the first unit. The demo therefore exercises that path from its first second.

### Credentials belong to the launcher, and topology belongs on the command line

`GraphDB.from_env()` already reads `GRAPHDB_URL` / `GRAPHDB_USERNAME` / `GRAPHDB_PASSWORD` /
`GRAPHDB_REPOSITORY`, so the environment is the established credential transport. The launcher holds
them and injects them into the environment of the children that talk to the graph — middleware,
controller, monitor. **PLC processes never receive them.** A mock PLC cannot reach the graph, even
by accident. That asymmetry is what scenario 3 demonstrates. The process boundary enforces it, and
not discipline.

Everything else is a command-line flag: unit number, resource IRI, broker address. The launcher
prints the line it runs. A person can copy-paste any one line, and run that process alone under a
debugger. That affordance is why containerisation was ruled out of scope. The config transport
should not quietly give it back.

Note the asymmetry in who needs what: the **only** process that must be told where the broker is, is
the PLC. A middleware reads its broker address out of the graph, which is scenario 3's central
claim.

### Ports are allocated by whoever binds them

A child allocates its own free port and binds it, so the allocate-hand-off-bind race disappears. The
reporting channel already exists for the processes that matter. Registration writes `svc:address`.
The controller and the launcher then learn a middleware's address the way they learn everything
else. Only the PLC panel needs a channel of its own, because the graph deliberately omits it. It
prints one line on stdout, and the launcher parses it.

Every port except the launcher's is therefore dynamic. That makes the launcher's index page
load-bearing, and not decorative. It is how a person finds anything.

### The frontend must be separable enough to point at the backend

The demo teaches through a run. Its UIs carry tooltips that name the source files worth a read.
Those files are always backend files. That only works if the split is real. So the PLC process is
`transfer_unit.py`: MQTT, state and the publish loop, with no HTTP anywhere. The panel is
`panel.py`: routes and templates, with no MQTT, no topic and no asyncio primitive. The two talk
through a narrow surface of public methods on the PLC object.

This is why the panel is FastAPI on the PLC's own event loop rather than Flask on a thread. A
threaded panel has two options, and both are bad. It reaches into the PLC's internal dictionaries,
which is the bleed the split prevents. Or it carries loop-hop ceremony in every handler. One
omission there is a silent hang, and not an error. On one loop, a handler simply awaits a public
method and the frontend file contains no concurrency machinery at all.

A static guard test enforces the split, in the manner of
`tests/test_examples_serve_their_middlewares.py`. The separation is a property a reader can trust.
It is not an intention that the next edit can quietly undo.

## Consequences

- **Teardown is ordered.** The launcher SIGTERMs middleware children first, so each deregisters
  while its PLC is still answering, then the PLC processes. It waits, SIGKILLs stragglers, and
  reports what did not exit. Killing PLCs first would leave every middleware erroring at a dead peer
  during its last seconds. The shutdown logic itself stays in the library — the launcher only sends
  signals.
- **The port half of #20 becomes a prerequisite.** Self-allocation is exactly what that ticket
  describes. Its host-IP half is not needed: this demo is localhost.
- **The controller does not spawn anything.** Adding a unit is done from the launcher's UI. The
  controller demonstrates one thing. A unit that appeared after its start needs no restart and no
  configuration. That is a graph-discovery property and the actual claim being made.
- **Every middleware gains an activity feed.** Runtime coverage on the existing named loggers:
  value in, setpoint out, heartbeat written, PUT applied. An opt-in ring-buffer handler sits behind
  an SSE `/activity` route on the instance's own app. It is library-level, so the controller and
  the monitor inherit it. The library composes into products it was not shaped around. This ADR
  demonstrates that claim, and does not assert it. The feed shows the *machinery*. The monitor
  shows *resource state*. Those stay separate.
- **`demo/transferunits/` is a new home.** `examples/` keeps the simple linear walkthrough scripts
  (scenarios 1 and 2). `demo/` holds runnable multi-process scenarios, each with its own README.
  `examples/scenario3_transferunit.py` and its notebook retire when the factory lands, replaced
  rather than repaired.
- **ADR 0022 is relied upon, not changed.** Two flavours on one unit already have distinct Service
  nodes. This ADR is what finally puts them in distinct processes.
- Ontology terms are unaffected — no new vocabulary enters, so ADR 0021 is untouched.

Decided on wayfinder ticket #58, under map #57.

---

**Amendment (2026-07-31, milestone 1 on map #57).** The target topology stays **2N+3**. Milestone
1 runs **2N+2**, because the monitor defers to milestone 2 (wayfinder ticket #59). Etienne's
reason: build the minimum example, make it run, and add the monitor against working code. Nothing
else in this ADR changes. The launcher still spawns one process per participant, still injects
credentials into graph-side children only, and still stops the middleware before its PLC.

**Correction to a consequence above.** This ADR states that "ADR 0022 is relied upon, not changed.
Two flavours on one unit already have distinct Service nodes." That is not true today.
`mint_service_iri` (`registration.py:52`) still returns `{resource_iri}_service`, a pure function
of the resource, and `middleware.py:187` calls it that way. ADR 0022 is **written and not
implemented**. Issue #47 implements it, and it stays open on map #24.

The correction has no effect on milestone 1, which runs one middleware instance per unit. It is a
hard prerequisite for the monitor. A monitor rooted at a unit's own IRI would mint the unit's
Service node. It would overwrite `svc:address` with its own address. It would then deregister the
unit on its own shutdown. Wire #47 as a blocker before ticket #59 is taken up.

---

**Amendment (2026-07-31, ticket #60).** The directory is **`demo/transferunits/`**, a real Python
package. This ADR wrote the directory as `demo/TransferUnits/` and the runner as
`python -m demo.transferunits.middleware`. Those two disagree, and a directory named
`TransferUnits` does not import as `transferunits`. The copy-pasteable command line is the one
that must work, so the directory follows it. The consequence above now reads
`demo/transferunits/`.

**What ADR 0030 adds.** This ADR states that the launcher owns the seed and mints the IRIs. ADR
0030 fixes what it mints and what it writes. Each unit gets an index-derived IRI. The ADR 0023
topic scheme stays unchanged. A live-factory probe runs before the clear. A control station
individual joins the units, in a class the demo owns.

**One claim above is narrowed.** This ADR states that seeded units and runtime-added units take
the same path, "because there is only one path". Milestone 1 has only the seed path, because #35
defers. The claim stays true, and it stays unproven until #35 lands.

**The broker.** This ADR states that the PLC is the only process that must be told where the
broker is. That stays correct. ADR 0031 adds a port to the broker metadata the middleware reads
from the graph, so the launcher can put a broker on a free port.
