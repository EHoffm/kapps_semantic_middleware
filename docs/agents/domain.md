# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** — read ADRs that touch the area you are about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files do not exist, **proceed silently**. Do not flag their absence. Do not suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

This repo is **multi-context** (`CONTEXT-MAP.md` exists at the root, as of 2026-07-14). Current contexts:

```
/
├── CONTEXT-MAP.md
├── docs/
│   ├── adr/                                  ← system-wide decisions (e.g. dependency policy)
│   └── prd/                                  ← "Module Requirements" context: PRDs on sibling repos, not this repo's own architecture
├── src/kapps_semantic_middleware/
│   ├── CONTEXT.md                            ← "Core Middleware" context
│   ├── docs/adr/
│   └── shacl_interop/
│       ├── CONTEXT.md                        ← "SHACL Interop" context (temporary scaffolding)
│       └── docs/adr/
└── examples/
    ├── CONTEXT.md                            ← "Example Scenarios" context
    └── docs/adr/
```

If this structure changes later (new context added, one removed), this file and `CONTEXT-MAP.md` should be updated together.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the relevant context's `CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

If the concept you need is not in the glossary yet, that is a signal — either you are inventing language the project does not use (reconsider) or there is a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md — but worth reopening because…_
