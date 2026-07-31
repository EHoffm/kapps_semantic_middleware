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

The library's shutdown handling already exists and is correct: `middleware.py` registers
`_deregister_service`, `_stop_heartbeat` and `_stop_sweep` as `on_shutdown` callbacks, so a
resource-mode instance removes its own reachability and stops its loops when the ASGI lifespan
shuts down.

It has never run. The serving idiom in `examples/` and `tests/` puts `uvicorn.Server.run()` on a
daemon thread, and uvicorn declines to install signal handlers off the main thread — verbatim from
`uvicorn/server.py`:

```python
# Signals can only be listened to from the main thread.
if threading.current_thread() is not threading.main_thread():
    yield
    return
```

No handler means SIGTERM never reaches the lifespan shutdown, so none of the three callbacks fire.
Scenarios 1 and 2 leave their Service individuals in the graph on every exit. The bug is not in the
shutdown code. It is in the process shape around it. Giving each middleware its own process, with
uvicorn on the main thread, is what turns an existing feature on.

The same shape dissolves the deadlock behind the unserved scenario-3 walkthrough: one loop per
process means the loop that wires the MQTT connectors is the loop that drives them.

### The launcher is scaffolding, and must stay outside the semantic world

The demo starts on an empty repository. A real factory does not: its TransferUnits are already
there, installed and registered long before any controller starts. The launcher exists purely to
manufacture that initial situation — seed the graph, start the processes — and it is therefore a
stand-in for reality rather than a participant in it.

Registering it as a `cfc:Resource` with a provisioning `cfc:Capability` was considered, and is
tempting: the controller would then reach it through ADR 0002 capability resolution with no
configured endpoint anywhere, and ADR 0009 would make a spawn request durable for free. It was
rejected because it asserts something false. Provisioning a machine is not a semantic-middleware
concern. Nobody dispatches an Operation to bolt a conveyor to the floor. Putting the launcher in the
graph would teach a viewer that the middleware does something it does not do.

The cost is accepted honestly: the launcher's own address is configuration rather than discovery. It
is the only such address in the system, and it belongs to the one component that is not part of what
is being demonstrated.

### The seed is the launcher's job, because the launcher decides N

Which triples exist depends on how many units are spawned, so seeding cannot be a step that runs
before the launcher and hands it a fixed world. The launcher mints the unit IRIs, writes the ABox,
and then starts the processes that inhabit it — one authority for the shape of the factory.

This also removes a split the map was worried about: seeded units and runtime-added units take the
**same** path, because there is only one path. A unit added ten minutes in is provisioned by the
same code that provisioned the first one, so the demo exercises that path from its first second.

### Credentials belong to the launcher; topology belongs on the command line

`GraphDB.from_env()` already reads `GRAPHDB_URL` / `GRAPHDB_USERNAME` / `GRAPHDB_PASSWORD` /
`GRAPHDB_REPOSITORY`, so the environment is the established credential transport. The launcher holds
them and injects them into the environment of the children that talk to the graph — middleware,
controller, monitor. **PLC processes never receive them.** A mock PLC that cannot reach the graph
even by accident is the asymmetry scenario 3 exists to demonstrate, enforced by process boundary
rather than by discipline.

Everything else — unit number, resource IRI, broker address — is a command-line flag, because the
launcher prints the line it runs and any one of them can be copy-pasted to run that process alone
under a debugger. That affordance is why containerisation was ruled out of scope. The config
transport should not quietly give it back.

Note the asymmetry in who needs what: the **only** process that must be told where the broker is, is
the PLC. A middleware reads its broker address out of the graph, which is scenario 3's central
claim.

### Ports are allocated by whoever binds them

A child allocates its own free port and binds it, so the allocate-hand-off-bind race disappears. The
reporting channel already exists for the processes that matter: registration writes `svc:address`,
so the controller and the launcher learn a middleware's address the way they learn everything else.
Only the PLC panel, which is deliberately absent from the graph, needs a channel of its own — one
line on stdout, parsed by the launcher.

The consequence is that every port except the launcher's is dynamic, which makes the launcher's
index page load-bearing rather than decorative: it is how a human finds anything.

### The frontend must be separable enough to point at the backend

The demo teaches by being run: its UIs carry tooltips naming the source files worth reading, and
those are always backend files. That only works if the split is real, so the PLC process is written
as `transfer_unit.py` (MQTT, state, publish loop; no HTTP anywhere) and `panel.py` (routes and
templates; no MQTT, no topics, no asyncio primitives), talking through a narrow surface of public
methods on the PLC object.

This is why the panel is FastAPI on the PLC's own event loop rather than Flask on a thread. A
threaded panel must either reach into the PLC's internal dictionaries — which is the bleed the split
exists to prevent — or carry loop-hopping ceremony in every handler, where one omission is a silent
hang rather than an error. On one loop, a handler simply awaits a public method and the frontend
file contains no concurrency machinery at all.

A static guard test enforces the split, in the manner of
`tests/test_examples_serve_their_middlewares.py`: the separation is a property a reader can rely on,
not an intention the next edit can quietly undo.

## Consequences

- **Teardown is ordered.** The launcher SIGTERMs middleware children first, so each deregisters
  while its PLC is still answering, then the PLC processes. It waits, SIGKILLs stragglers, and
  reports what did not exit. Killing PLCs first would leave every middleware erroring at a dead peer
  during its last seconds. The shutdown logic itself stays in the library — the launcher only sends
  signals.
- **The port half of #20 becomes a prerequisite.** Self-allocation is exactly what that ticket
  describes. Its host-IP half is not needed: this demo is localhost.
- **The controller does not spawn anything.** Adding a unit is done from the launcher's UI. What the
  controller demonstrates is that a unit which appeared after it started shows up with no restart
  and no configuration. That is a graph-discovery property and the actual claim being made.
- **Every middleware gains an activity feed.** Runtime coverage on the existing named loggers (value
  in, setpoint out, heartbeat written, PUT applied) plus an opt-in ring-buffer handler behind an SSE
  `/activity` route on the instance's own app. It is library-level, so the controller and monitor
  inherit it — the library composing into products it was not shaped around, demonstrated rather
  than asserted. It shows the *machinery*. The monitor shows *resource state*. Those stay separate.
- **`demo/TransferUnits/` is a new home.** `examples/` keeps the simple linear walkthrough scripts
  (scenarios 1 and 2). `demo/` holds runnable multi-process scenarios, each with its own README.
  `examples/scenario3_transferunit.py` and its notebook retire when the factory lands, replaced
  rather than repaired.
- **ADR 0022 is relied upon, not changed.** Two flavours on one unit already have distinct Service
  nodes. This ADR is what finally puts them in distinct processes.
- Ontology terms are unaffected — no new vocabulary enters, so ADR 0021 is untouched.

Decided on wayfinder ticket #58, under map #57.
