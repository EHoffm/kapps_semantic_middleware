# SHACL Interop

One of four contexts in this repo — see `/CONTEXT-MAP.md` at the repo root for the others.

Temporary scaffolding (see
`src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`)
that generates
and parses the SHACL shapes describing a Workflow or StateProperty class's precondition/
outcome, in place of the native `kapps_ogm` support this logic properly belongs in (see
`docs/prd/kapps-ogm-shacl-support.md` at the repo root). Deliberately kept separate from Core
Middleware so it can be deleted wholesale, without untangling it from Core Middleware's own
vocabulary, once `kapps_ogm` absorbs this capability.

## Language

**Precondition shape**:
The `sh:property` group reachable via `svc:precondition` on a Workflow class's `sh:NodeShape`
(`sh:targetClass`), describing the arguments a Workflow's underlying Python function requires.
Derived from the function's type hints, not hand-authored.
_Avoid_: Argument schema, input schema (those describe the Python-level shape; Precondition
shape is specifically its SHACL-RDF encoding).

**Outcome shape**:
The `sh:property` group reachable via `svc:outcome` on the same `sh:NodeShape`, describing the
Workflow's return value. Same derivation and encoding pattern as Precondition shape.

**Signature-derived shape**:
The general mechanism this context implements: turning a Python function's type hints into a
SHACL `NodeShape` (empty for zero-argument functions, which is the only case exercised so
far — see Example Scenarios). Targets the Workflow/StateProperty *class*, never a specific
instance, for the same fleet-scale reason Core Middleware requires pre-existing types at all.
