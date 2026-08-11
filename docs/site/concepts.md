# Concepts

:::{warning}
Placeholder. The page inventory is settled on #116; writing it is the
information-architecture ticket's job.
:::

## Why a knowledge graph sits in the middle

A conventional middleware moves values between a machine and an application.
This one first asks the graph *what the machine is* and *what it can do*, then
moves the values. Registration, discovery and execution are three views of the
same triples.

## The three modes

See {py:class}`kapps_semantic_middleware.modes.Mode` for which are implemented.

## Reasoning is not optional

The middleware relies on the triple store's reasoner: `include_implicit`
defaults to querying `FROM onto:implicit`, and both ontologies carry
`owl:imports`. A store without a reasoner returns fewer triples and fails
quietly, which is why GraphDB — not an in-memory graph — is a prerequisite.

:::{note}
This is the reasoning that ruled a second backend out of v0.1.0 on the map.
:::
