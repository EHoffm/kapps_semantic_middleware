"""A middleware runner for a single TransferUnit.

It serves exactly one resource-mode SemanticMiddleware instance. Uvicorn runs on
the main thread, and owns the process event loop. This is load-bearing:
It enables signal handling. This enables the library's
on_shutdown deregistration fire (ADR 0029). The process reads GRAPHDB_* from
its environment and derives its resource IRI from the unit index.
"""

from __future__ import annotations

import argparse
import asyncio
import socket

from graph_db_interface import GraphDB
from kapps_ogm import OGM
from kapps_ogm.utils.class_scope import ClassScope

from kapps_semantic_middleware import Mode, SemanticMiddleware

from . import seed


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
    host: str, port: int, middleware: SemanticMiddleware, sock: socket.socket | None = None
) -> None:
    """Run the FastAPI server directly on this loop (uvicorn on the main thread)."""
    config = __import__("uvicorn").Config(
        app=middleware.app, host=host, port=port, log_level="warning"
    )
    server = __import__("uvicorn").Server(config=config)
    await server.serve(sockets=[sock] if sock is not None else None)


async def main() -> None:
    parser = argparse.ArgumentParser(description="A TransferUnit middleware runner")
    parser.add_argument(
        "--unit-index", type=int, default=1, help="The unit index (default: 1)"
    )
    parser.add_argument(
        "--resource-iri",
        type=str,
        default=None,
        help="The Resource IRI (default: derived from --unit-index)",
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
        args.resource_iri
        if args.resource_iri is not None
        else str(seed._mint_transfer_unit_iri(args.unit_index))
    )

    db = GraphDB.from_env()
    ogm = OGM(db=db)
    class_scope = ClassScope.from_property_chains(
        [
            [seed.TU_HAS_CONVEYOR_BELT, seed.TU_HAS_CONVEYOR_SPEED],
            [seed.TU_HAS_LIGHT_BARRIER, seed.TU_IS_OCCUPIED],
        ]
    )

    middleware = SemanticMiddleware(
        mode=Mode.RESOURCE,
        resource_iri=resource_iri,
        service_class=str(seed.TRANSFER_UNIT_SERVICE_CLASS),
        ogm=ogm,
        host=args.host,
        port=port,
        class_scope=class_scope,
        autoregister_connectors=True,
    )

    # No broker flag here: the connector reads the broker address (and, per
    # ADR 0031, an absent port means 1883) off the graph at wiring time.
    print(f"Middleware running on http://{args.host}:{port}/", flush=True)
    await run_server(args.host, port, middleware, sock)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
