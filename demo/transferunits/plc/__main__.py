"""Entry point for running the TransferUnit PLC with panel.

Takes --unit-index, --broker, --broker-port, --panel-port.
--panel-port of 0 asks OS for free port.
Prints one line to stdout with bound port.
FastAPI runs on PLC event loop (not uvicorn on thread).
"""

from __future__ import annotations

import argparse
import asyncio
import socket

from .transfer_unit import TransferUnit
from .panel import app, configure_plc


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


async def run_server(host: str, port: int) -> None:
    """Run the FastAPI server using asyncio directly."""
    config = __import__("uvicorn").Config(app=app, host=host, port=port, log_level="warning")
    server = __import__("uvicorn").Server(config=config)
    await server.serve()


async def main() -> None:
    parser = argparse.ArgumentParser(description="TransferUnit PLC with panel")
    parser.add_argument("--unit-index", type=int, default=1, help="Unit index (default: 1)")
    parser.add_argument("--broker", type=str, default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--broker-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--panel-port", type=int, default=0, help="Panel HTTP port (0 = free)")
    args = parser.parse_args()

    # Determine panel port
    panel_port = args.panel_port if args.panel_port != 0 else find_free_port()

    # Create and configure PLC
    plc = TransferUnit(
        unit_index=args.unit_index,
        broker=args.broker,
        port=args.broker_port,
    )
    configure_plc(plc)

    # Start PLC and server concurrently
    async with plc:
        print(f"Panel running on http://127.0.0.1:{panel_port}/", flush=True)
        await run_server("127.0.0.1", panel_port)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass