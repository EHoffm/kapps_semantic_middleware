# Heartbeat on resource-mode services, sweeper as watchdog mode

Every resource-mode `SemanticMiddleware` runs an internal periodic Workflow
(`interval=..., on_startup=True`, using `aas_middleware`'s existing interval-workflow support)
that refreshes an `svc:lastHeartbeat` timestamp on its own Service individual. Separately,
`mode="watchdog"` instances run a sweep loop that queries for Service individuals whose
`svc:lastHeartbeat` has gone stale and deregisters them (removes `svc:address` and their
Workflows'/StateProperties' `svc:endpoint`) using the same removal logic as graceful shutdown.

**Why**: graceful-shutdown-only deregistration leaves the graph permanently pointing at dead
processes after any crash, kill, or power loss — a standard "stale service registry entry"
failure mode, and one the paper names explicitly as a known limitation of the architecture
as evaluated ("middleware-level heartbeat supervision, complemented by a triple store-side
watchdog that removes stale discovery triples when a resource-bound middleware instance
falls silent"). The paper's own phrasing already splits this into two responsibilities —
per-instance heartbeat and centralized sweeping — which is why it became a third `mode`
rather than a flag on resource mode: a sweeper has no resource to wrap and, unlike resource
or server mode, isn't answering requests at all, it's the one process type whose entire job
is background maintenance of the registry.

**Consequence**: a real deployment needs at least one running `watchdog`-mode instance for
the "no dangling registrations" guarantee to hold in practice — it is not automatic just
because heartbeat code exists. Heartbeat interval and staleness threshold are runtime
parameters, not architectural choices, and are expected to need tuning once this runs against
a real fleet of concurrent instances rather than the two-scenario demonstration this session
was built against.
