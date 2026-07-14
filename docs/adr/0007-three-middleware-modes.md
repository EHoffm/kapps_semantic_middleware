# Three middleware modes: resource, server, watchdog

`SemanticMiddleware` takes a `mode` constructor parameter with three values:

- `"resource"` (built first): wraps one `resource_iri`. User-registered `@workflow`/`@state`
  functions are the REST-facing surface. Built-in functionality (`execute`, CRUD via the
  OGM) is exposed only as plain Python methods, not REST routes.
- `"server"` (not yet implemented): wraps no resource. `execute`/CRUD *are* the REST
  surface — e.g. a future "product server" whose entire purpose is answering
  `fetch`/`ClassScope` requests against the graph for other services.
- `"watchdog"` (built alongside resource mode): wraps no resource, exposes little to no REST
  surface, and instead runs a sweep loop that deregisters (removes `address`/`endpoint` from)
  Service individuals whose heartbeat has gone stale.

**Why**: these three shapes were each raised independently during design (a bare
hello-world function; a future data-serving service with no physical resource; a
liveness-sweeping process with no resource *and* no meaningful REST surface) and turned out
not to be variations on one shape but three genuinely different answers to "what is this
middleware instance for." Rather than let that surface as three unrelated classes or three
sets of ad hoc constructor flags, `mode` makes the distinction explicit and exhaustive at
construction time. `execute`/CRUD existing as Python-only methods in resource mode but as the
REST surface in server mode follows directly from what each mode's purpose actually is: in
resource mode, workflows are the point and `execute` is plumbing a resource-mode instance
uses internally (e.g. to trigger *other* resources' capabilities); in server mode, there are
no workflows, so `execute`/CRUD have nothing to hide behind.

**Consequence**: `server` and `watchdog`-as-a-concept both existed as scope only at design
time; `watchdog`'s sweep logic was pulled into this session's build scope alongside resource
mode (see [[adr-0009]]) once its two-part decomposition (heartbeat + sweeper) became clear.
`server` mode remains a documented, reserved mode value with no implementation yet.
