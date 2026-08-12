# kapps_semantic_middleware

Semantic middleware for industrial data integration, built on `aas_middleware`. A resource's state
is described in a knowledge graph as a protocol-interface **parameter**, and the middleware wires
that description to a real device — discovering peers, serving them over REST, and keeping the
graph and the device in step.

## Setting up

Everything this project needs resolves from PyPI.

```bash
pip install kapps-semantic-middleware
```

To also get the scenario notebooks and the TransferUnit factory demo:

```bash
pip install "kapps-semantic-middleware[demonstrations]"
```

Working from a checkout instead? `uv sync` installs the same set, and
`pytest -m "not live"` runs the tier that needs no GraphDB.

## Run a local GraphDB (Docker)

Docker is needed only for the examples and the demo, never for the library itself.

1. Start GraphDB and create the repository:
   ```bash
   cd docker && docker compose up -d
   ```
   GraphDB runs on http://localhost:7200. The `kapps-demo` repository is created automatically.
   This works identically on Linux, macOS, and Windows.

2. Set the environment variables:
   ```bash
   cp .env.example .env
   ```
   Or export the four `GRAPHDB_*` variables manually. The examples and demo read them to reach
   GraphDB.

3. Reset or isolate the repository:
   ```bash
   docker compose down -v
   ```
   This wipes the throwaway repository. The demo re-seeds it on the next run.

**Warning:** Never point `GRAPHDB_URL` or `GRAPHDB_REPOSITORY` at a shared GraphDB instance.
The demo wipes whatever repository you name.

## Where things are

| | |
|---|---|
| [`CONTEXT-MAP.md`](CONTEXT-MAP.md) | **Start here.** The five contexts and how they relate. |
| `src/kapps_semantic_middleware/` | The library. |
| [`AGENTS.md`](AGENTS.md) | Consumption rules and the mechanics index, for an agent building against this. |
| [`docs/mechanics/`](docs/mechanics/) | How each mechanic is used, one page each. |
| `demo/transferunits/` | The factory demo: N units, a controller, one launcher command. |
| `examples/` | Scenario 1 (operation coordination) and scenario 2 (direct state). |

### Which of the three do you want?

The code lives in three places, and the one to open depends on what you came for.

- **`src/kapps_semantic_middleware/`** — the reference implementation. It is generic, and it names
  no domain term. Read this to use the middleware in your own project.
- **`demo/transferunits/`** — the runnable factory. Read this to watch the middleware work end to
  end, and to drive it from a browser. One command starts it.
- **`examples/`** — notebooks for scenario 1 and scenario 2, each self-contained, plus the seed
  logic they share with the test suite. Read this for the smallest possible introduction.

## The demo

`demo/transferunits/` stands up a small factory and you drive it from a browser: one process per
mock PLC, one per middleware instance, plus a controller that discovers every unit *in the graph*
and drives it over REST. See [`demo/transferunits/README.md`](demo/transferunits/README.md).

It needs a reachable GraphDB (`GRAPHDB_*` in the environment) and will write to the repository those
variables point at. For a one-command local option, see [Run a local GraphDB (Docker)](#run-a-local-graphdb-docker).
