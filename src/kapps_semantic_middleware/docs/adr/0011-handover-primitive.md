# Handover is a mode-aware context manager, not an Operation

Change-of-possession is a core middleware primitive `mw.handover(mode, workpiece, counterpart)`,
invoked by domain code *while executing* an operation — it is **not** itself dispatched as an
Operation through the queue. It is a transaction context manager (ADR 0010):

- `__enter__` runs exactly **two precondition checks, outside the transaction**: the caller
  currently possesses the workpiece, and the counterpart carries the complementary
  `mes:hasHandoverAbility` for the mode. There is deliberately **no destination-free check** —
  possession is not universally `maxCount 1`.
- the **body is domain-owned**: physical transport / preparation and all counterpart
  coordination. The core never references `execute()`. The body may itself open a `request(...)`
  dispatch to drive the counterpart.
- `__exit__` commits the **one atomic possession switch** on clean exit (a single OGM
  `DELETE/INSERT`, ADR 0008), and aborts with no switch on exception.

Mode is one of three complementary ability pairs from Elfaham & Epple's intralogistics meta-model
(*at–Automatisierungstechnik* 2020): **Put↔Receive** (source active), **Pick↔Release**
(destination active), **Pass↔Retrieve** (both active). Handover is modeled as a *timeless
administrative possession switch* preceded by a *timed physical preparation* phase — which is
exactly why preparation is the (timed) body and the switch is the (timeless) atomic commit.

**Why**: transport ≠ handover, and modeling the possession switch as its own queued Operation
would force a request/response handshake for what is a single administrative fact. A context
manager instead lets the physical work be ordinary domain code bracketed by a check and an
atomic, SHACL-safe commit — and the "exactly one possessor" cardinality is enforced *at commit
time by SHACL* as the backstop, which is only sound because the switch is a single atomic
transaction (ADR 0008), never a remove-then-add that is transiently zero-possessor.

**Consequence**: v1 models possession (`mes:hasPossession`/`mes:isPossessedBy`) and a
`mes:hasHandoverAbility` tag with six enumerated individuals (`Put`/`Receive`/`Pick`/`Release`/
`Pass`/`Retrieve`), all in the **MES ontology** (ADR 0012) — no ability *classes*, no liveness,
no `Place`, no topology / possible-positions-of-handover model. The per-mode responsibility
semantics and the two-instance synchronization of `Pass↔Retrieve` are deliberately deferred
([#9](https://github.com/EHoffm/kapps_semantic_middleware/issues/9)); v1 keeps all such
coordination in the domain-owned body. Promotes the resolution of
[#7](https://github.com/EHoffm/kapps_semantic_middleware/issues/7).

---

**Amendment (2026-07-21, #18 — possession is Core's reified `PossessionState`).** Verified
against Core 0.9.0: Core already models possession as a **reified, time-bound
`cfc:PossessionState`** (`cfc:hasPossessor` Resource→PossessionState, `cfc:hasPossessedWorkpiece`
Workpiece→PossessionState), with a Core restriction that a **Workpiece has exactly one**
`hasPossessedWorkpiece` state. So this project no longer uses the (now-removed) binary
`mes:hasPossession`. The handover primitive reads and writes **Core's** possession model:

- `__enter__` "caller possesses the workpiece" check: is there a PossessionState the workpiece
  points to whose possessor is the caller — `workpiece cfc:hasPossessedWorkpiece ?ps .
  caller cfc:hasPossessor ?ps`.
- `__exit__` switch: mint a new `cfc:PossessionState`; **append** the counterpart's
  `cfc:hasPossessor` link to it as an atomic insertion (a resource may possess several
  workpieces, so this is an insert via the graph_db_interface, *not* an OGM replace that would
  clobber its other possessions — ADR 0008); then **re-point** the workpiece's cardinality-1
  `cfc:hasPossessedWorkpiece` to it in one OGM `DELETE/INSERT` (the update path). The append is
  ordered before the re-point, so a failed re-point leaves the prior possession fully intact.
  The workpiece points to exactly one PossessionState throughout — the cardinality-bearing step
  (the re-point) is a single atomic commit, so the backstop is never transiently violated. The
  old PossessionState is kept as **implicit history** (the workpiece no longer points to it). No
  OWL-Time interval is written in v1 (deferred). The "possessed by exactly one" backstop is
  **Core's own** Workpiece cardinality-1 on `cfc:hasPossessedWorkpiece`, enforced at commit by
  SHACL — not asserted by this project.

The `mes:hasHandoverAbility` complementary-ability check in `__enter__` is unchanged (Core has
no handover-ability concept). See ADR 0012 amendment.
