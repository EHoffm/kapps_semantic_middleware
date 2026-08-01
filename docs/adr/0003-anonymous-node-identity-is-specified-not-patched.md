# Anonymous-node identity is a `kapps_ogm` defect, but it exceeds the bugfix allowance — so we specify it

`kapps_ogm` discards the identity of the anonymous node behind a `COMPLEX` property at read. It mints a
fresh one at write. It diffs whole blank-node groups. The result is that any commit touches a
parameter. This orphans the connection metadata the ClassSpec never declared. No OGM write path can put
that metadata there in the first place. It is a defect. Unlike root ADR 0002's arity check, the fix is
not a local correction. It changes identity, projection and specification on the OGM's central write
path. Root ADR 0001 permits **bugfixes** in sibling checkouts, not redesigns of them. So this one is
written up as a PRD. It is handed to the owner rather than patched in our checkout.

## Why

Three things had to be true at once for a local patch to be the right call. Only the first is:

- **It is a defect, not a feature request.** A fetch-then-commit round trip with no modification
  should leave the graph byte-identical. Today it relocates every blank node. It destroys triples the
  schema did not anticipate. The read path deliberately tolerates exactly those triples under
  the Open World Assumption.
- **It is not local.** The fix touches `_fetch_complex_property`, `Node`, the pydantic model
  generation, `_value_to_triples`, `diff`, and `PropertySpec.specify`. Carry that as a patch in a
  path dependency would fork the OGM in all but name. The next upstream release would either
  clobber it or silently diverge from it.
- **Its semantics are a judgement call with a reviewer.** Whether an anonymous node may be given an
  IRI at all is an RDF-semantics decision (RDF 1.1 §3.5). This project is published with the
  people who work on blank-node semantics on the author list. That decision belongs with the ontology
  engineer and the OGM owner, not in a downstream patch.

The counterpart decision is that the **`graph_db_interface` half is** a bugfix. It is treated as one:
`triples_update` builds two separate blank-node→variable maps. A blank node appearing on both sides
of an update renders as two different variables. The INSERT side always mints a new store node. A
node present on both sides *is* the same node. That is a local, self-contained correction. It is
implemented on a branch with a changelog entry, per root ADR 0001.

## Consequences

- `docs/prd/kapps-ogm-anonymous-node-identity.md` is the specification of record. Tracking issues
  are on the `SAWeindel/kapps_ogm` board. This mirrors how the SHACL and visual-toolbox requirements were
  handled (`#49`, `#50`).
- Scenario 3's implementation set depends on OGM work we do not own. The seeded
  `examples/transferunit.ttl` keeps standing in for "a previous run instantiated this" until it lands.
- Our checkout of `kapps_ogm` stays unpatched. It can track upstream.
- Extends root ADR 0002 rather than replaces it: the arity check is one part of the same package (see
  the amendment there).

Raised by wayfinder ticket #52 under map #24.
