"""The control station runner for the factory demo.

It serves the Controller (ticket #43) as a resource-mode middleware.
Uvicorn runs on the main thread, and owns the process event loop, the same
way the middleware runner does (ADR 0029). The process reads GRAPHDB_* from
its environment.
"""

from __future__ import annotations

import argparse
import asyncio
import socket

from graph_db_interface import GraphDB
from kapps_ogm import OGM

from . import seed
from .controller import Controller


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
    )

    print(f"The control station runs on http://{args.host}:{port}/", flush=True)
    await run_server(args.host, port, controller, sock)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
