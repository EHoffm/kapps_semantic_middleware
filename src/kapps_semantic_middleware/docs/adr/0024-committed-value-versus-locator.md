# Committed value or locator is the domain's choice; the middleware is agnostic

Whether a parameter's value **lives in the graph** or the graph merely records **where the value lives**
is a decision for the domain subproject, not a rule the middleware enforces. Both patterns are supported
and neither is privileged:

- **Committed value** — the data point changes slowly (say once a day). The domain expert loads the
  resource datamodel, registers connectors, and commits on change. The graph holds the value. No
  `@state` is involved, because the update frequency does not warrant it.
- **Locator** — the data point changes fast. The graph holds the parameter's *metadata* — unit, access
  mode, topic, broker — and never its value. The live value exists only in the datamodel and over REST.

The middleware neither strips values on the way to the graph nor refuses to commit them.

**Scenario 3 is a locator.** Conveyor speeds and light-barrier states change continuously, so the
extended `transferunit.ttl` (#25) authors **no `inf:hasValue` literals** on parameter blanknodes. The
`rdfs:range` restriction still declares `inf:hasValue`, so the datamodel field exists; the instance
simply leaves it empty.

## Why

### "The live value is never persisted" was a pattern, described as an invariant

ADR 0015 states that "the live value is still never *persisted to the graph*", and the Parameter glossary
entry repeated it. Read as a middleware guarantee, that would require the write path to know which fields
are live and strip them — and it would forbid a legitimate use we should support. It is really a property
of the **locator** pattern, which ADR 0015 was describing because the scenario in front of it was a
fast-changing one.

Enforcing it would also break the middleware's ontology-agnosticism. A parameter with a daily update
rate is well served by committing the value: the graph becomes queryable for it, no connector needs to
stay live to answer, and the domain expert avoids `@state` altogether. Refusing that commit — or silently
dropping it — would push a design decision that belongs to twenty domain subprojects into the core.

### Empty is representable, so the locator needs no extra vocabulary

The `hasValue` literals in the upstream TransferUnit instance data are **pre-middleware test
scaffolding**, authored when there was nothing to supply a live value. Removing them is not a loss: a
parameter with no reading yet materializes as `hasValue: []` and `NodeValidator` treats a `min_count`
shortfall as a warning under the Open World Assumption, not an error (#29). So "no reading has arrived"
is expressible in the data model as it stands, with no flag, no sentinel and no nullability vocabulary.

This also removes an ambiguity the IT-OT boundary exists to prevent. If the graph seeded a value, a peer
reading a speed shortly after startup would receive a number authored in a `.ttl` file, indistinguishable
from a sensor reading. Under the locator pattern there is nothing to mistake.

### The distinction is behavioural, so it needs no mechanism

Both patterns may register connectors; they differ only in whether the domain code commits. Nothing in
the ontology or the middleware has to mark which is in use, and no new term is needed to express the
choice. That is the cheapest possible way to support both, and it keeps the recognition model (ADR 0020)
untouched.

> **Blocked for the committed-value pattern until SAWeindel/kapps_ogm#4 lands (#28).**
> Committing a parameter today **orphans its connection metadata**: `to_triples` mints a fresh blank
> node every serialization and `diff` replaces whole blank-node groups, so the old node — still holding
> the topic and broker the ClassSpec never declared — is unlinked and a metadata-less node takes its
> place. The locator pattern is unaffected, because it never commits values. A domain choosing the
> committed-value pattern must wait for the fix, or keep its connection metadata on a node it does not
> commit.

## Consequences

- Amends **ADR 0015**: "the live value is never persisted to the graph" is scoped to the locator pattern
  rather than stated as a middleware invariant. ADR 0015 make no such claim and are
  unaffected.
- **#25** authors `transferunit.ttl` with parameter metadata but **no value literals**. Ordinary complex
  properties that are not interface parameters — a manufacturer, a serial number — keep their literals;
  they are data, not parameters (ADR 0020).
- A parameter reads as `hasValue: []` between startup and the device's first publish. Consumers must
  handle an empty value; it means "not yet observed", not "zero".
- `_dump_resource_datamodel` still writes the whole datamodel, live values included, into
  `svc:failureState` as an opaque JSON literal on failure. That is a deliberate diagnostic exception
  (ADR 0009) and not affected by either pattern — it records triples about an Operation, not about the
  parameter.
- Domain guidance rather than core enforcement: a subproject choosing the committed-value pattern should
  say so, because a reader who finds values in the graph will otherwise assume they are stale.

Resolves part of wayfinder ticket #28 under map #24.
