# kapps_semantic_middleware

Semantic middleware for industrial data integration, built on `aas_middleware`. A resource's state
is described in a knowledge graph as a protocol-interface **parameter**, and the middleware wires
that description to a real device — discovering peers, serving them over REST, and keeping the
graph and the device in step.

## Setting up

**Read [SIBLINGS.md](SIBLINGS.md) first.** This project depends on three sibling repositories as
editable path checkouts, all three are on unmerged feature branches, and `uv.lock` records none of
that. A `main` checkout of any sibling fails, each in its own way.

**You need KIT GitLab access to build this today.** One sibling, `aas_middleware_inf`, lives on a
private KIT GitLab instance and has no public mirror. Without an account there, `uv sync` cannot
resolve it, and no amount of local setup works around that.

```bash
python scripts/check_siblings.py   # verify the three siblings
uv sync
pytest -m "not live"               # the tier that needs no GraphDB
```

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

**Warning:** Never point `GRAPHDB_URL` at a shared GraphDB instance. The demo wipes and re-seeds the
repository it uses on every run.

The repository itself is not yours to choose: the demo and the examples pin `kapps-demo`, the one
`docker compose` creates, and the test suite pins its own. A `GRAPHDB_REPOSITORY` in your environment
is ignored by all of them, so a stray value cannot direct a wipe at a repository you care about
(issue #146). Only `GRAPHDB_URL`, `GRAPHDB_USERNAME` and `GRAPHDB_PASSWORD` are read.

## Where things are

| | |
|---|---|
| [`CONTEXT-MAP.md`](CONTEXT-MAP.md) | **Start here.** The five contexts, and which ADR governs which. |
| `src/kapps_semantic_middleware/` | The library. |
| `src/kapps_semantic_middleware/docs/adr/` | Core Middleware and TransferUnit Factory decision records. |
| `docs/adr/` | Root records — decisions above every context, including the sibling dependency policy. |
| `demo/transferunits/` | The factory demo: N units, a controller, one launcher command. |
| `examples/` | Scenario 1 (operation coordination) and scenario 2 (direct state). |
| [`docs/agents/`](docs/agents/) | Issue tracker, triage labels, and domain conventions for agents. |

### Which of the three do you want?

The code lives in three places, and the one to open depends on what you came for.

- **`src/kapps_semantic_middleware/`** — the reference implementation. It is generic, and it names
  no domain term. Read this to use the middleware in your own project.
- **`demo/transferunits/`** — the runnable factory. Read this to watch the middleware work end to
  end, and to drive it from a browser. One command starts it.
- **`examples/`** — scenario 1 and scenario 2, each self-contained, as both a Jupyter notebook and
  a plain-Python script, plus the seed logic they share with the test suite. Read this for the
  smallest possible introduction. When installed from PyPI, get them with
  `pip install "kapps-semantic-middleware[examples]"` and run `kapps-examples` to copy them into a
  directory you can edit and run; add the `[notebooks]` extra to open the `.ipynb` in Jupyter.

## The demo

`demo/transferunits/` stands up a small factory and you drive it from a browser: one process per
mock PLC, one per middleware instance, plus a controller that discovers every unit *in the graph*
and drives it over REST. See [`demo/transferunits/README.md`](demo/transferunits/README.md).

It needs a reachable GraphDB (`GRAPHDB_*` in the environment) and will write to the repository those
variables point at. For a one-command local option, see [Run a local GraphDB (Docker)](#run-a-local-graphdb-docker).

## Acknowledgements

This package is developed as part of the INF subproject of the CRC 1574: Circular Factory for the
Perpetual Product. This work is therefore supported by the Deutsche Forschungsgemeinschaft (DFG,
German Research Foundation) [grant-number: SFB-1574-471687386].
