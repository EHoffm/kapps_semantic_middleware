# kapps_semantic_middleware

Semantic middleware for industrial data integration, built on `aas_middleware`. A resource's state
is described in a knowledge graph as a protocol-interface **parameter**, and the middleware wires
that description to a real device — discovering peers, serving them over REST, and keeping the
graph and the device in step.

## Setting up

**Read [SIBLINGS.md](SIBLINGS.md) first.** This project depends on three sibling repositories as
editable path checkouts, all three are on unmerged feature branches, and `uv.lock` records none of
that. A `main` checkout of any sibling fails, each in its own way.

```bash
python scripts/check_siblings.py   # verify the three siblings
uv sync
pytest -m "not live"               # the tier that needs no GraphDB
```

## Where things are

| | |
|---|---|
| [`CONTEXT-MAP.md`](CONTEXT-MAP.md) | **Start here.** The four contexts, and which ADR governs which. |
| `src/kapps_semantic_middleware/` | The library. |
| `src/kapps_semantic_middleware/docs/adr/` | Core Middleware and TransferUnit Factory decision records. |
| `docs/adr/` | Root records — decisions above every context, including the sibling dependency policy. |
| `demo/transferunits/` | The factory demo: N units, a controller, one launcher command. |
| `examples/` | Scenario 1 (operation coordination) and scenario 2 (direct state). |
| [`docs/agents/`](docs/agents/) | Issue tracker, triage labels, and domain conventions for agents. |

## The demo

`demo/transferunits/` stands up a small factory and you drive it from a browser: one process per
mock PLC, one per middleware instance, plus a controller that discovers every unit *in the graph*
and drives it over REST. See [`demo/transferunits/README.md`](demo/transferunits/README.md).

It needs a reachable GraphDB (`GRAPHDB_*` in the environment) and will write to the repository those
variables point at.
