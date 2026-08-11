# Agent configuration (development only)

Development configuration for agents working **on** this repository. Nothing under `docs/agents/`
ships: the release allowlist excludes this directory, and the release hygiene gate fails the push
if a file matching `docs/agents/` reaches the release tree.

Agents building **against** the middleware want [`AGENTS.md`](../../AGENTS.md) instead — the
consumption rules, the import table, and the `docs/mechanics/` set. That file does ship.

## Issue tracker

Issues live in GitHub Issues (`EHoffm/kapps_semantic_middleware`, via the `gh` CLI). External PRs
are also pulled into the triage queue. See [`issue-tracker.md`](issue-tracker.md).

## Triage labels

All five canonical role names used as-is: `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`. See [`triage-labels.md`](triage-labels.md).

## Domain docs

Multi-context layout: `CONTEXT-MAP.md` at the root points to five contexts (Core Middleware, SHACL
Interop, Example Scenarios, TransferUnit Factory, Module Requirements). See
[`domain.md`](domain.md).
