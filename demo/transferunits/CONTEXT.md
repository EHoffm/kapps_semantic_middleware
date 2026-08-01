# TransferUnit Factory

This module is one of five contexts in this repository. See `/CONTEXT-MAP.md` at the root for the others.

This is a runnable multi-process demonstration. It stands up a small factory of TransferUnits and a
controller, and a person drives it from a browser. Each participant is a separate process
(ADR 0029).

Its decisions are **ADR 0029, ADR 0030 and ADR 0032**. They live in the ADR directory of the Core
Middleware context, in one shared sequence: `../../src/kapps_semantic_middleware/docs/adr/`. The root
`CONTEXT-MAP.md` records which context each ADR governs.

**Root ADR 0004 governs what belongs here.** Every part of a scenario lives in this directory. The
library holds generic functions only. The monitor, the controller and the TransferUnit resource logic
are parts of scenario 3.

## Language

**Factory**:
The whole demonstration as it runs: N TransferUnits, a controller, a monitor, and the Launcher
that starts them.
_Avoid_: demo, scenario 3, setup

**Unit index**:
This is the integer from 1 to N that identifies one TransferUnit. Every IRI and every MQTT topic of that
unit derives from it (ADR 0030).
_Avoid_: unit number, unit id, n

**Launcher**:
This process builds the initial situation and starts every other process. It is plain
infrastructure and it never appears in the knowledge graph (ADR 0029).
_Avoid_: supervisor, orchestrator, bootstrapper

**Runner**:
This entry point serves exactly one instance of resource-mode middleware for one TransferUnit.
_Avoid_: middleware script, worker

**Control station**:
This is the controller's Resource individual in the graph. It carries no controllable parameter, and
it appears in its own discovery list.
_Avoid_: controller resource, planner, operator station

**Panel**:
A mock PLC serves this UI for itself. There is one per PLC process. Distinct from the controller UI, which
reaches units through the middleware.
_Avoid_: device UI, unit page

**Live factory**:
A state of the graph, not of the host: a Service carries an address and a heartbeat inside the
staleness window. The Launcher refuses to clear a live factory (ADR 0030).
_Avoid_: running factory, active factory
