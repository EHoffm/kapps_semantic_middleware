"""Workflow and state handlers for the example scenarios.

These live in an importable module (rather than inline in the notebooks) for a
concrete reason: ``@workflow`` runs each function through aas_middleware's
typeguard-based instrumentation, which reads the function's *module source*. A
function defined in a Jupyter cell belongs to ``__main__``, which has no source
file, so that instrumentation fails. Defining the handlers here gives them a real
module source and keeps the shared in-memory door state in one place.
"""

from __future__ import annotations

# --- Scenario 1 -------------------------------------------------------------- #


def hello_world() -> str:
    """The most basic workflow: return a greeting."""
    return "hello world"


# --- Scenario 2 (door) ------------------------------------------------------- #

# In-memory door state — mutated by the workflows, read by the state getter.
# Deliberately NOT stored in the knowledge graph.
_door = {"status": "closed"}


def door_open() -> str:
    """Workflow: open the door (mutates in-memory state)."""
    _door["status"] = "opened"
    return "opened"


def door_close() -> str:
    """Workflow: close the door (mutates in-memory state)."""
    _door["status"] = "closed"
    return "closed"


def door_status() -> str:
    """State getter: the door's current status, served live from memory."""
    return _door["status"]
