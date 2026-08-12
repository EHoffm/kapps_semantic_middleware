# kapps-semantic-middleware

Semantic middleware for industrial data integration. It registers equipment and
its capabilities in a knowledge graph, discovers what a machine can do by
querying that graph, and executes operations over MQTT and HTTP.

:::{note}
This is a **placeholder site**, built to settle the docs pipeline on
[#116](https://github.com/EHoffm/kapps_semantic_middleware/issues/116).
The page inventory below is the shape [#117](https://github.com/EHoffm/kapps_semantic_middleware/issues/117)
argued for; filling it is a separate ticket.
:::

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`book;1.5em;sd-mr-1` Concepts
:link: concepts
:link-type: doc

Why a knowledge graph sits in the middle, what the three modes mean, and why
the reasoner is not optional.
:::

:::{grid-item-card} {octicon}`rocket;1.5em;sd-mr-1` Quickstart
:link: quickstart
:link-type: doc

Install the library, bring up GraphDB with one `docker compose up`, and copy
the notebooks somewhere you can edit them.
:::

:::{grid-item-card} {octicon}`beaker;1.5em;sd-mr-1` Scenarios
:link: scenarios/index
:link-type: doc

Three worked examples in increasing size: Hello World, the door and robot, and
the six-process TransferUnit factory.
:::

:::{grid-item-card} {octicon}`code;1.5em;sd-mr-1` API reference
:link: reference/index
:link-type: doc

Fourteen modules, generated from the docstrings in `src/`.
:::

::::

## Where to start

**Concepts** first, not installation. Unlike a plain API client, this middleware
needs a triple store and a broker running before anything works, so the reasons
have to land before the commands do.

```{toctree}
:hidden:
:maxdepth: 2

concepts
quickstart
scenarios/index
reference/index
```
