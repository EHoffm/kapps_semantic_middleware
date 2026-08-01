# Committed value or locator is the domain's choice. The middleware is agnostic

Whether a parameter's value lives in the graph is a decision for the domain subproject. The graph may merely record where the value lives instead. The middleware enforces no rule here. Both patterns are supported and neither is privileged:

- **Committed value** — the data point changes slowly (say once a day). The domain expert loads the resource datamodel, registers connectors, and commits on change. The graph holds the value. No `@state` is involved, because the update frequency does not warrant it.
- **Locator** — the data point changes fast. The graph holds the parameter's *metadata* — unit, access mode, topic, broker — and never its value. The live value exists only in the datamodel and over REST.

The middleware does not strip values on the way to the graph. The middleware does not refuse to commit them.

**Scenario 3 is a locator.** Conveyor speeds and light-barrier states change continuously, so the extended `transferunit.ttl` (#25) authors **no `inf:hasValue` literals** on parameter blanknodes. The `rdfs:range` restriction still declares `inf:hasValue`, so the datamodel field exists. The instance simply leaves it empty.

## Why

### "The live value is never persisted" was a pattern, described as an invariant

ADR 0015 states that "the live value is still never *persisted to the graph*", and the Parameter glossary entry repeated it. Read as a middleware guarantee, that statement would require the write path to know which fields are live. It would also require the path to strip them. This would forbid a legitimate use we should support. It is really a property of the **locator** pattern, which ADR 0015 described because the scenario in front of it was a fast-changing one.

Enforcing it would also break the middleware's ontology-agnosticism. A parameter with a daily update rate is well served by committing the value. The graph becomes queryable for it. No connector needs to stay live to answer. The domain expert avoids `@state` altogether. Refusing that commit — or silently dropping it — would push a design decision into the core. That decision belongs to twenty domain subprojects.

### Empty is representable, so the locator needs no extra vocabulary

The `hasValue` literals in the upstream TransferUnit instance data are **pre-middleware test scaffolding**. They were authored when there did not exist anything to supply a live value. Removing them does not cause loss. A parameter with no reading yet materializes as `hasValue: []`. `NodeValidator` treats a `min_count` shortfall as a warning under the Open World Assumption, not an error (#29). So "no reading has arrived" is expressible in the data model as it stands. It needs no flag, no sentinel and no nullability vocabulary.

This also removes an ambiguity the IT-OT boundary exists to prevent. If the graph seeded a value, a peer reading a speed shortly after startup would receive a number. That number was authored in a `.ttl` file. It was indistinguishable from a sensor reading. Under the locator pattern there does not exist anything to mistake.

### The distinction is behavioural, so it needs no mechanism

Both patterns may register connectors. They differ only in whether the domain code commits. Nothing in the ontology or the middleware has to mark which is in use. No new term is needed to express the choice. That is the cheapest possible way to support both. It keeps the recognition model (ADR 0020) untouched.

> **Blocked for the committed-value pattern until SAWeindel/kapps_ogm#4 lands (#28).**
> Committing a parameter today **orphans its connection metadata**. `to_triples` mints a fresh blank node every serialization. `diff` replaces whole blank-node groups. The old node — still holding the topic and broker the ClassSpec never declared — is unlinked. A metadata-less node takes its place. The locator pattern is unaffected, because it never commits values. A domain choosing the committed-value pattern must wait for the fix. It may keep its connection metadata on a node it does not commit.

## Consequences

- Amends **ADR 0015**: "the live value is never persisted to the graph" applies to the locator pattern. It is not stated as a middleware invariant. ADR 0015 makes no such claim and is unaffected.
- **#25** authors `transferunit.ttl` with parameter metadata but **no value literals**. Ordinary complex properties that are not interface parameters — a manufacturer, a serial number — keep their literals. They are data, not parameters (ADR 0020).
- A parameter reads as `hasValue: []` between startup and the device's first publish. Consumers must handle an empty value. It means "not yet observed", not "zero".
- `_dump_resource_datamodel` still writes the whole datamodel, live values included, into `svc:failureState` as an opaque JSON literal on failure. That is a deliberate diagnostic exception (ADR 0009). Either pattern does not affect it. It records triples about an Operation, not about the parameter.
- Domain guidance rather than core enforcement. A subproject choosing the committed-value pattern should say so. Otherwise a reader who finds values in the graph will assume they are stale.

Resolves part of wayfinder ticket #28 under map #24.
