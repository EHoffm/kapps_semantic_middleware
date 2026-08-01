"""The control station runner for the factory demo.

Serves the Controller (ticket #43) as a resource-mode middleware.
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


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


async def run_server(host: str, port: int, controller: Controller) -> None:
    """Run the FastAPI server on this loop (uvicorn on the main thread)."""
    config = __import__("uvicorn").Config(
        app=controller.app, host=host, port=port, log_level="warning"
    )
    server = __import__("uvicorn").Server(config=config)
    await server.serve()


async def main() -> None:
    parser = argparse.ArgumentParser(description="The control station runner")
    parser.add_argument(
        "--resource-iri",
        type=str,
        default=None,
        help="Resource IRI (default: the seeded control station)",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = free)")
    args = parser.parse_args()

    port = args.port if args.port != 0 else find_free_port()

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

    print(f"Control station running on http://{args.host}:{port}/", flush=True)
    await run_server(args.host, port, controller)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
