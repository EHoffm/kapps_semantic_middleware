# Example notebooks are self-contained: dummy user, cleared repository, seeded ontologies

Every example Jupyter notebook (scenario 1, scenario 2, and future ones) runs against a
dedicated dummy GraphDB user/repository. Its first cells clear that repository entirely. They
then insert exactly the ontology modules the example needs (Core subset, the `svc:` module, the
example's domain ontology, and pre-authored Capability/Workflow/Service classes). They also
seed whatever instance data the scenario assumes as its starting point, before any example logic
runs.

**Why**: without this, a notebook has only two options. First, it can run against the
production knowledge graph. Then every re-run becomes a live write against production state.
The notebook's behavior then depends on whatever state production happens to be in when it
runs. This is neither reproducible nor safe to hand to someone who explores the middleware for the
first time. Second, it can silently assume a bespoke local setup. The reader then has to
reconstruct that setup by hand before the notebook does anything meaningful. Neither option is
acceptable for a document whose whole purpose is to let someone unfamiliar with the system run
it and see what happens.

**Consequence**: every example needs its ontology/seed-data prerequisites made fully explicit
and scripted, not just documented in prose. Each notebook therefore doubles as a minimal,
runnable specification of exactly what ground-truth ontology a given scenario requires. This
directly exercises the pre-existing-class policy from
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`. The
clear-and-seed step is where a scenario's Capability/Workflow/Service classes actually get
authored into the graph, before the middleware that depends on them can start.
