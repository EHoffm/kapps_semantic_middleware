# Store the callable endpoint on both Service and Workflow/StateProperty

The paper describes the middleware populating a single `address` property on the *Service*
individual, from which a workflow's endpoint is presumably reconstructed by convention. This
project stores `svc:address` on the Service (the base URL) *and* writes the full, directly
callable `svc:endpoint` on each Workflow and StateProperty individual as well.

**Why**: a caller resolving "what URL do I invoke for this specific Workflow" (as `execute()`
must, given an Operation IRI several hops away from any Service) would otherwise need to
walk `Workflow -> isWorkflowOf -> Service -> address` and then know, out-of-band, the
route-naming convention to append (`/workflows/{name}/execute`). That convention knowledge
would have to live somewhere — either duplicated into every caller, or centralized in a
shared library function every caller depends on. Storing the resolved endpoint directly on
the Workflow trades a small amount of duplication (the same host:port appears in both
`address` and every `endpoint` under it) for removing that coupling entirely: any caller with
just a Workflow IRI can invoke it with one property read.

**Consequence**: deregistration must remove *both* properties to preserve the paper's
invariant that "no workflow exposed by the service appears as invokeable" once
deregistered — removing only `Service.address` would leave stale-but-present
`Workflow.endpoint` triples that still resolve.
