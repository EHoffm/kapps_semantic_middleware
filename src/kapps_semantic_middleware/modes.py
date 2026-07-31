"""The three middleware modes as constants rather than bare strings (ADR 0005, #21).

``SemanticMiddleware(mode=...)`` took a plain ``str`` and validated it against a tuple written
out at the call site. A typo produced a ``ValueError`` at construction — which is at least loud —
but nothing made the valid values discoverable, and every comparison in the class restated one of
the literals.

A ``str`` subclass rather than a plain ``Enum``, deliberately: every existing caller passes
``mode="resource"``, and the scenarios, tests and notebooks are full of it. Subclassing ``str``
keeps all of that working unchanged — ``Mode.RESOURCE == "resource"`` is true, and so is
``mode in (Mode.RESOURCE, Mode.WATCHDOG)`` for a caller who passed the bare string. The constant
is the better way to say it; the string does not stop being a way to say it.
"""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """A middleware instance's mode. See ADR 0005 for what each one means."""

    RESOURCE = "resource"
    """Wraps one ``resource_iri``: registers a Service, serves its workflows and parameters,
    and holds a heartbeat. The only mode with runtime consequence today."""

    SERVER = "server"
    """Reserved — data-serving with no physical resource. Not implemented; constructing one
    raises. Ruled out of scope for the scenario-3 controller in ADR 0005's third amendment,
    because a controller consumes a graph rather than serving one."""

    WATCHDOG = "watchdog"
    """Reserved — centralized liveness sweeping (ADR 0007). Sweeps stale Services; registers
    nothing of its own."""

    def __str__(self) -> str:
        # Without this, an f-string renders "Mode.RESOURCE" rather than "resource", which
        # would change every log line and error message that interpolates a mode.
        return self.value


ALL = tuple(Mode)
"""Every valid mode, for validation and for error messages that list the alternatives."""
