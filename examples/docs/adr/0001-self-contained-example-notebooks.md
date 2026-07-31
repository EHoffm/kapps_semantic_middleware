# Example notebooks are self-contained: dummy user, cleared repository, seeded ontologies

Every example Jupyter notebook (scenario 1, scenario 2, and future ones) runs against a
dedicated dummy GraphDB user/repository. Its first cells clear that repository entirely, then
insert exactly the ontology modules the example needs (Core subset, the `svc:` module, the
example's own domain ontology and pre-authored Capability/Workflow/Service classes) and seed
whatever instance data the scenario assumes as its starting point, before any example logic
runs.

**Why**: without this, a notebook either has to run against the real production knowledge
graph (making every re-run of the notebook a live write against production state, and making
the notebook's behavior depend on whatever state production happens to be in when it is run —
neither reproducible nor safe to hand to someone exploring the middleware for the first time)
or silently assume a bespoke local setup the reader has to reconstruct by hand before the
notebook does anything meaningful. Neither is acceptable for a document whose whole purpose is
letting someone unfamiliar with the system run it and see what happens.

**Consequence**: every example needs its ontology/seed-data prerequisites made fully explicit
and scripted, not just documented in prose — which also means each notebook doubles as a
minimal, runnable specification of exactly what ground-truth ontology a given scenario
requires (directly exercising the pre-existing-class policy from
`src/kapps_semantic_middleware/docs/adr/0003-ontology-as-ground-truth-for-types.md`: the
clear-and-seed step is where a scenario's Capability/Workflow/Service classes actually get
authored into the graph before the middleware that depends on them can start).
