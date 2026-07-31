# The programmatic surface is transaction context managers

The way domain Python code drives the middleware (as opposed to REST callers) is a family of
**context managers, each of which is one transaction**. The pattern is: preconditions checked
in `__enter__` *outside* the transaction; the domain's own code runs in the body; the atomic
commit happens in `__exit__` on clean exit, and **reverts + re-raises on exception**. Every
**write-bearing** entrypoint takes this shape — `handover` (possession switch), `claim_next`
(pull-and-run of a queued Operation), and `request` (caller-side dispatch: create the Operation
and fire the receiver's event trigger). Pure **reads** (`fetch`, `resolve`, state GET) stay immediate
method calls. There is no transaction to guard.

**Why**: this directly operationalizes the project's standing constraint — *every graph write
is a transaction; precondition checks happen before it; a failed transaction reverts* — as the
actual API shape, rather than leaving it a discipline each call site must remember. It is also
the pattern the two systems this team already knows converge on. SQLAlchemy's unit of work is
`with session.begin(): ...` — flush-and-commit on clean exit, roll back on exception — which is
*exactly* the handover context manager (#7) generalized. Kadi-APY (the RDM platform in the same
research cluster) uses `with KadiManager() as manager:` for session **lifecycle** and immediate
per-call writes for everything else — which is why reads and the middleware's own
start/register→deregister/stop lifecycle stay plain, and only the guarded units of work become
`with`-blocks. Considered and rejected: (a) CM only for handover, leaving pull-and-run to set
status and dump state by hand — loses the automatic, uniform revert-on-failure exactly where a
physical body can raise; (b) every call a CM including reads — ceremony with no transaction to
protect.

**Consequence**: `execute()` (the receiver-side event trigger) and the REST endpoints are *not* part
of this surface — they are the wire/REST face (ADR 0009, ADR 0005). The context managers are the
in-process face for the domain code co-located with a resource. The handover core still never
references `execute()` (#7): its body is domain-owned and may itself open a `request(...)` to
drive a counterpart. New write-bearing middleware capabilities are expected to arrive as
context managers of this same shape. All commits inside `__exit__` still go through the OGM's
single atomic `DELETE/INSERT` write path (ADR 0008), so the cardinality-constrained possession
switch is never transiently invalid.
