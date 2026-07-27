# Production code carries fully back-resolvable IRIs; pretty-printing is display-only

Every IRI in production code — REST path segments, datamodel field names, `svc:endpoint` triples —
stays the **full mangled form** (`IRI.lined`), which is mechanically reversible to the original IRI.
Human-readable rendering is a **pretty-print function on the `IRI` class**, used by the Flask UIs and
by Swagger where supported. It may be lossy, because it is never parsed.

Two scoping rules ride with this:

- **No domain IRIs in the middleware core.** Domain vocabulary belongs in the domain-expert portion
  of a scenario, never in `src/kapps_semantic_middleware/`.
- **A connector may hardcode only its own ontology's terms.** The MQTT connector may name
  `inf:hasMQTTTopic`; it may not name `tu:hasConveyorSpeed`.

## Why

### Reversibility is the property that matters

The generated surface today is, verbatim:

```
GET|PUT|DELETE  /https_c__s__s_www_d_sfb1574_d_kit_d_edu_s_ontologies_s_TransferUnit_h_TransferUnit/{item_id}
```

That is 78 characters for one segment, and the recursive router (ADR 0017) stacks three of them. The
obvious fix — use the IRI fragment as the segment — was rejected. A shortened segment must be mapped
back to an IRI to serve a request, and any shortening that can collide (two namespaces sharing a
fragment) or that depends on a prefix map turns a mechanical transformation into a lookup that can
drift, silently, exactly when the consolidation (#39) rewrites namespaces. The mangled form has no
such failure mode: it is a total, invertible function of the IRI.

The cost is genuinely low. Consumers never hand-write these URLs — they read `svc:endpoint` from the
graph and GET the datamodel they are served (ADR 0018). The only readers who suffer are humans, and
they are looking at a UI or at Swagger, both of which can render a pretty form without anyone parsing
it back.

### The core cannot know the domain, or it stops being a middleware

The core's job is to serve *any* resource whose ontology follows the patterns. A `tu:` IRI compiled
into it would make the TransferUnit special — the scenario would stop being a learning vehicle and
become a hardcoded case. Verified at the time of writing: the only namespaces appearing in `src/` are
`cfc:` Core, `svc:` Service, MES and W3C standards.

The same rule applied to connectors is what makes the registry work at all (ADR 0020). A connector
that named domain properties would need one entry per resource type; a connector that names only its
own protocol vocabulary serves every resource that speaks that protocol.

## Consequences

- The `IRI` class gains a display/pretty-print method. It is a rendering concern; nothing parses it,
  and it carries no correctness weight.
- The Flask UIs (#31, #33) render pretty names and hold mangled ones. Swagger gets the pretty form
  only where the framework allows a display override.
- `svc:endpoint` values are stable under everything except an actual IRI change. The consolidation
  (#39) rewrites namespaces and therefore does rewrite endpoint triples — accepted, because those
  triples are written by the middleware at registration and rewritten on the next startup, not
  authored by hand.
- Reviewing core for stray domain IRIs is a cheap, mechanical check and worth keeping cheap.

Resolves part of wayfinder ticket #29 under map #24.
