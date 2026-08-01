# TransferUnit Factory

A running multi-process demo (ADR 0029). One command seeds a knowledge graph, spawns N
TransferUnits, and a controller that discovers and drives them purely through the graph.

Milestone 1 runs **2N+2** processes: one PLC+panel and one middleware per unit, plus one control
station. (The target topology is 2N+3 — a monitor joins in milestone 2; see
`../../src/kapps_semantic_middleware/docs/adr/0029-the-factory-is-one-process-per-participant.md`.)

```
launcher            fixed port, the only bookmarkable one; seeds the graph, spawns, tears down
├── plc-1           MockTransferUnit + its panel     (no GRAPHDB_* in its environment, ever)
├── middleware-1    SemanticMiddleware                (uvicorn owns the process's only loop)
├── plc-2           …
├── middleware-2    …
└── control-station SemanticMiddleware wrapping the Controller (#43), northbound consumer
```

## Run it

Requires a running GraphDB with `GRAPHDB_URL` / `GRAPHDB_USERNAME` / `GRAPHDB_PASSWORD` /
`GRAPHDB_REPOSITORY` set in the environment. Nothing else needs to be running first — the launcher
starts a local MQTT broker itself if none is listening on `127.0.0.1:1883`.

```
python -m demo.transferunits.launcher --units 2
```

- `--units N` — how many TransferUnits to seed and spawn (default 2).
- `--force` — clear and reseed even if a live factory is already running.

Every child's command line is printed as it's spawned, so any one process can be copy-pasted into
a debugger and run alone against the already-seeded graph, e.g. for unit 2:

```
python -m demo.transferunits.plc --unit-index 2 --broker 127.0.0.1 --broker-port 1883 --panel-port 0
python -m demo.transferunits.middleware --unit-index 2 --port 0
python -m demo.transferunits.control_station --port 0
```

Press Ctrl+C to stop. Teardown is ordered: every middleware and the control station are SIGTERMed
first, so each deregisters (`svc:Service` removed) while its PLC is still answering; then the PLCs.

## Layout

- `launcher.py` — seeds, spawns, tracks, and tears down every child process.
- `middleware.py` — the runner: one resource-mode `SemanticMiddleware` per unit.
- `control_station.py` — the runner for the Controller (#43), wrapped as middleware.
- `controller.py` — discovery + dispatch logic: lists resources by type, drives any unit found.
- `seed.py` — index-derived IRI minting and MQTT topics for N units (ADR 0030), plus the one
  control station individual.
- `plc/` — the mock PLC and its own panel UI, one process per unit (ADR 0029's process split).
- `factory.ttl`, `transferunit.ttl` — the demo's own ontology (control station class, TransferUnit
  shape).

See `CONTEXT.md` for the domain language (Factory, Unit index, Launcher, Runner, Control station,
Panel, Live factory) and the ADRs it points at for the decisions behind this shape.
