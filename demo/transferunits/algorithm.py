"""The Control Expert's own algorithm code for the TransferUnit factory demo.

This module is the **only** place in this demo allowed to name domain terms like
``tu:TransferUnit``, ``tu:hasConveyorBelt``, etc. The generic ``Controller`` mechanism
in ``controller.py`` deliberately knows nothing about any domain class -- it executes
the view, wires connectors, and loads datamodels, but the *what* (which class, which
heuristic) lives here, not there. This separation realizes ADR 0033's core claim: the
Control Expert and the TransferUnit Expert never meet, and neither imports the other's
code. The knowledge graph is the entire contract.

The algorithm itself is deliberately meaningless -- it demonstrates reach, not real
control. It reads a barrier on one unit and echoes that unit's conveyor speed onto
another unit's conveyor ("set a speed from a random other unit's speed", per ADR 0033
step 5). A real material flow controller would route parcels across units by reading
barriers and deciding which unit to trigger; this demo does none of that because
building a real one is domain work, not middleware work. The graph carries no plant
layout, so nothing here can route anything, and that is the MVP boundary rather than
an oversight.

Usage::

    # In control_station.py's main():
    hits = controller.view(build_view_query())
    controller.wire_view(hits, class_scope=unit_class_scope())
    # ... server starts, datamodels load into controller.units ...
    # Background loop runs run_algorithm_once every 5 seconds.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from graph_db_interface import IRI
from kapps_ogm.utils.class_scope import ClassScope

from kapps_semantic_middleware.vocabulary import INF, SVC

from . import seed
from .controller import Controller

logger = logging.getLogger(__name__)


def build_view_query() -> str:
    """Build the SPARQL SELECT query that finds live, even-indexed TransferUnits.

    This realizes ADR 0033 step 1: the view is the query, and the query text supplies
    the domain class and any heuristic. ``Controller.view()`` runs this verbatim and
    returns every IRI it binds to ``?resource``. Nothing in ``controller.py`` assumes
    a domain class or a column beyond ``?resource`` itself.

    The heuristic here -- unit index is even -- is deliberately arbitrary. It is chosen
    because it visibly returns roughly half the factory when N units are seeded, making
    the demo's behavior easy to verify by inspection. A real algorithm would narrow by
    area of the plant, topology, or workload instead.

    Live means the resource's Service carries ``svc:address``. The query joins from
    ``?resource`` to its Service via ``svc:isServiceOf``, then requires ``?addr`` to be
    bound. The unit index is extracted from the IRI's local name (e.g.
    ``...#TransferUnit4`` -> ``4``) and tested for evenness arithmetically: SPARQL 1.1
    has no ``%`` modulo operator, so this computes
    ``xsd:integer(?suffix) - 2 * FLOOR(xsd:integer(?suffix) / 2)``, which is 0 for an
    even suffix and 1 for an odd one.

    Returns:
        A SPARQL ``SELECT ?resource`` query string.
    """
    return f"""
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?resource WHERE {{
        ?resource a <{seed.TRANSFER_UNIT_CLASS}> .
        ?svc <{SVC.isServiceOf}> ?resource .
        ?svc <{SVC.address}> ?addr .
        BIND(STRAFTER(STR(?resource), "#TransferUnit") AS ?suffix)
        FILTER(?suffix != "" &&
               (xsd:integer(?suffix) - 2 * FLOOR(xsd:integer(?suffix) / 2)) = 0)
    }}
    """


def unit_class_scope() -> ClassScope:
    """Return the ClassScope that roots at tu:TransferUnit and reaches belt/barrier parameters.

    This is the Control Expert's own view of one hit's shape (ADR 0018, ADR 0033). It must
    match what the unit's own middleware uses (``demo/transferunits/middleware.py``'s own
    ``class_scope``), because the expert needs to see the same nested parameters the unit
    exposes. Built from ``seed``'s constants so the demo package remains self-contained
    (ADR 0030: "the duplication ends in its own commit").

    Returns:
        A ClassScope with two property chains: belt->speed and barrier->occupied.
    """
    return ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )


async def run_algorithm_once(controller: Controller) -> Optional[IRI]:
    """Execute one tick of the demonstration algorithm (ADR 0033 step 5).

    Deliberately meaningless -- it demonstrates reach, not real control. Picks two
    distinct unit IRIs at random from ``controller.units``, reads a barrier on the
    source (proving it was reachable), reads the source's conveyor speed, and echoes
    that speed onto the target's conveyor ("set a speed from a random other unit's
    speed", per ADR 0033). No HTTP call happens in this function's body -- only
    ``controller.push`` drives the assignment out.

    If fewer than 2 units are loaded, returns ``None`` and logs at DEBUG that there was
    nothing to drive yet. Otherwise logs at INFO the barrier reading and the
    source/target IRIs and speed value pushed.

    Args:
        controller: The Controller instance whose ``units`` dict holds the loaded
            datamodels.

    Returns:
        The target IRI that was pushed, or ``None`` if fewer than 2 units were loaded
        or either unit's shape was incomplete.
    """
    if len(controller.units) < 2:
        logger.debug("Fewer than 2 units loaded; nothing to drive yet.")
        return None

    unit_iris = list(controller.units.keys())
    source_iri_str, target_iri_str = random.sample(unit_iris, 2)
    source_iri = IRI(source_iri_str)
    target_iri = IRI(target_iri_str)

    source_unit = controller.units[source_iri_str]
    target_unit = controller.units[target_iri_str]

    # Read the source unit's first light barrier's isOccupied value (read-only, to
    # prove reachability per ADR 0033 step 4's "read a barrier").
    source_barriers = getattr(source_unit, seed.TU_HAS_LIGHT_BARRIER.lined)
    if source_barriers:
        occupied_param = getattr(source_barriers[0], seed.TU_IS_OCCUPIED.lined)
        if occupied_param:
            occupied_value = getattr(occupied_param[0], INF.hasValue.lined)
            logger.info("Barrier on %s reads %s", source_iri, occupied_value)

    # Read the source unit's first conveyor belt's current hasConveyorSpeed value.
    source_belts = getattr(source_unit, seed.TU_HAS_CONVEYOR_BELT.lined)
    if not source_belts:
        logger.warning("Source unit %s has no conveyor belts; skipping tick.", source_iri)
        return None
    source_speed_param = getattr(source_belts[0], seed.TU_HAS_CONVEYOR_SPEED.lined)
    if not source_speed_param:
        logger.warning("Source belt on %s has no speed parameter; skipping tick.", source_iri)
        return None
    speed_value = list(getattr(source_speed_param[0], INF.hasValue.lined))

    # Echo the source's speed onto the target unit's first conveyor belt. A fresh list
    # (not the source's own) -- the two units must not end up sharing one mutable list.
    target_belts = getattr(target_unit, seed.TU_HAS_CONVEYOR_BELT.lined)
    if not target_belts:
        logger.warning("Target unit %s has no conveyor belts; skipping tick.", target_iri)
        return None
    target_speed_param = getattr(target_belts[0], seed.TU_HAS_CONVEYOR_SPEED.lined)
    if not target_speed_param:
        logger.warning("Target belt on %s has no speed parameter; skipping tick.", target_iri)
        return None
    setattr(target_speed_param[0], INF.hasValue.lined, speed_value)

    # Drive the assignment out -- no HTTP call here, push() does the plumbing.
    await controller.push(target_iri)

    logger.info("Echoed speed %s from %s onto %s", speed_value, source_iri, target_iri)
    return target_iri


async def run_algorithm_loop(controller: Controller, *, interval: float = 5.0) -> None:
    """Run the algorithm periodically in the background, mirroring the heartbeat loop shape.

    An ``async def`` with ``try: while True: ... except asyncio.CancelledError: pass`` --
    the exact pattern ``SemanticMiddleware`` uses for its own heartbeat (see
    ``middleware.py``'s ``_heartbeat_loop``). ``interval`` defaults to 5.0 seconds,
    slower than the REST connector's own 2-second poll cadence (``rest_binding.py``'s
    ``DEFAULT_POLL_INTERVAL_SECONDS``), so a push has settled before the next tick reads
    anything.

    Args:
        controller: The Controller instance to run the algorithm against.
        interval: Seconds between ticks. Defaults to 5.0.
    """
    try:
        while True:
            await run_algorithm_once(controller)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
