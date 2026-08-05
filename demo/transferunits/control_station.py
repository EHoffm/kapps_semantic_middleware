"""The control station runner for the factory demo.

It serves the Controller (ticket #43) as a resource-mode middleware. Uvicorn runs on
the main thread, and owns the process event loop, the same way the middleware runner
does (ADR 0029). The process reads GRAPHDB_* from its environment.

The view mechanism (ADR 0033, ticket #80) now runs here: ``main()`` calls
``controller.view()`` with the algorithm's SPARQL query, then ``controller.wire_view()``
to recognize and register REST connectors for every hit. This must happen synchronously
before the server starts serving, because connector registration must precede the app's
lifespan connecting everything (see ``Controller.wire_view``'s docstring for why). Once
the app starts, each wired hit's northbound datamodel loads into ``controller.units``,
and a background loop runs the demonstration algorithm every few seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket

from graph_db_interface import GraphDB
from kapps_ogm import OGM

from . import algorithm, seed
from .controller import Controller

logger = logging.getLogger(__name__)


def bind_free_socket(host: str) -> socket.socket:
    """Bind and listen on an OS-assigned free port, without releasing it.

    Reading back a discovered port, closing the socket, and letting uvicorn bind a new
    one reopens the allocate-hand-off-bind race ADR 0029 credits self-allocation with
    removing -- another process could take the port in between. Handing uvicorn this same,
    still-listening socket instead of a bare port number closes that gap.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, 0))
    sock.listen(1)
    return sock


async def run_server(
    host: str, port: int, controller: Controller, sock: socket.socket | None = None
) -> None:
    """Run the FastAPI server on this loop (uvicorn on the main thread)."""
    config = __import__("uvicorn").Config(
        app=controller.app, host=host, port=port, log_level="warning"
    )
    server = __import__("uvicorn").Server(config=config)
    await server.serve(sockets=[sock] if sock is not None else None)


def _wire_algorithm(controller: Controller) -> None:
    """Register the demonstration algorithm's start-up/shutdown callback pair.

    Mirrors ``SemanticMiddleware``'s own heartbeat convention
    (``middleware.py``'s ``_start_heartbeat``/``_stop_heartbeat``): a background task
    created on ``on_start_up``, cancelled and awaited cleanly on ``on_shutdown``. The
    one-element list is the closure's box for the task object -- ``_start_algorithm``
    needs to *set* it, and a bare ``nonlocal`` has nothing to rebind across the two
    separately-registered callbacks otherwise.
    """
    algorithm_task: list[asyncio.Task] = []

    async def _start_algorithm() -> None:
        algorithm_task.append(asyncio.create_task(algorithm.run_algorithm_loop(controller)))

    async def _stop_algorithm() -> None:
        if algorithm_task:
            algorithm_task[0].cancel()
            try:
                await algorithm_task[0]
            except asyncio.CancelledError:
                pass

    controller.add_callback("on_start_up", _start_algorithm)
    controller.add_callback("on_shutdown", _stop_algorithm)


async def main() -> None:
    parser = argparse.ArgumentParser(description="The control station runner")
    parser.add_argument(
        "--resource-iri",
        type=str,
        default=None,
        help="Resource IRI (default: the seeded control station)",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="The host to bind")
    parser.add_argument("--port", type=int, default=0, help="The port to bind (0 = free)")
    args = parser.parse_args()

    if args.port == 0:
        sock = bind_free_socket(args.host)
        port = sock.getsockname()[1]
    else:
        sock, port = None, args.port

    resource_iri = (
        args.resource_iri if args.resource_iri is not None else str(seed.CONTROL_STATION)
    )

    db = GraphDB.from_env()
    ogm = OGM(db=db)

    controller = Controller(
        resource_iri=resource_iri,
        service_class=str(seed.CONTROL_STATION_SERVICE_CLASS),
        ogm=ogm,
        host=args.host,
        port=port,
        activity_feed=True,
    )

    # ADR 0033 steps 1-4: run the view, then wire a driving REST connector for every
    # hit. Synchronous, and before run_server -- connector registration must precede
    # the app's lifespan connecting everything (Controller.wire_view's own docstring).
    hits = controller.view(algorithm.build_view_query())
    logger.info("The view found %d live, even-indexed unit(s)", len(hits))
    controller.wire_view(hits, class_scope=algorithm.unit_class_scope())
    _wire_algorithm(controller)

    print(f"The control station runs on http://{args.host}:{port}/", flush=True)
    await run_server(args.host, port, controller, sock)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
