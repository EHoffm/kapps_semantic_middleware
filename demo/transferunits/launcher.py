"""Launcher for the multi-process TransferUnit factory.

Builds the initial situation (seeds the graph) and spawns every participant
process: one PLC and panel, and one middleware, per unit, plus one control
station. Credentials go only to graph-side children. A PLC process never
receives GRAPHDB_* (ADR 0029). Teardown is ordered: middleware and the
control station first, so each deregisters while its PLC still answers,
then the PLCs.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from graph_db_interface import GraphDB

from . import seed

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883


@dataclass
class ChildHandle:
    """Tracking information for one spawned child process."""

    pid: int
    kind: str  # "plc", "middleware", or "controller"
    unit_index: Optional[int]  # None for the controller
    cmdline: str
    address: Optional[str] = None


def _broker_listening(host: str = BROKER_HOST, port: int = BROKER_PORT) -> bool:
    """Check whether something already listens on host:port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect((host, port))
            return True
    except OSError:
        return False


def _start_broker() -> Optional[subprocess.Popen]:
    """Start an in-process amqtt broker on 127.0.0.1:1883, if nothing listens there.

    Runs in its own subprocess with its own asyncio loop. The config shape matches the mqtt_broker fixture in tests/conftest.py. It stays alive for the lifetime of the launcher. Returns None if a broker already answers —
    there is then nothing for this launcher to stop later.
    """
    if _broker_listening():
        return None

    script = (
        "import asyncio\n"
        "from amqtt.broker import Broker\n"
        "async def main():\n"
        "    broker = Broker({\n"
        "        'listeners': {'default': {'type': 'tcp', "
        f"'bind': '{BROKER_HOST}:{BROKER_PORT}', 'max_connections': 100}}}},\n"
        "        'sys_interval': 0,\n"
        "        'auth': {'allow-anonymous': True},\n"
        "        'topic-check': {'enabled': False},\n"
        "    })\n"
        "    await broker.start()\n"
        "    await asyncio.Event().wait()\n"
        "asyncio.run(main())\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _broker_listening():
            break
        time.sleep(0.1)
    return proc


def _strip_graphdb_env(env: dict) -> dict:
    """Return a copy of env without GRAPHDB_* variables."""
    return {k: v for k, v in env.items() if not k.startswith("GRAPHDB_")}


_PANEL_PORT_RE = re.compile(r":(\d+)/?\s*$")


def _spawn_plc(unit_index: int, broker: str = BROKER_HOST, broker_port: int = BROKER_PORT) -> ChildHandle:
    """Spawn a PLC and panel process for one unit.

    Its environment carries no GRAPHDB_* variable — enforced by construction,
    not by discipline (ADR 0029). Its panel address arrives as one line on
    stdout, since a PLC holds no graph credentials to register one itself.
    """
    cmdline = [
        sys.executable,
        "-m",
        "demo.transferunits.plc",
        "--unit-index",
        str(unit_index),
        "--broker",
        broker,
        "--broker-port",
        str(broker_port),
        "--panel-port",
        "0",
    ]
    cmdline_str = " ".join(cmdline)
    print(cmdline_str, flush=True)

    env = _strip_graphdb_env(os.environ.copy())
    proc = subprocess.Popen(
        cmdline,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        bufsize=1,
    )

    panel_port = None
    for line in proc.stdout:
        if "Panel running on http://" in line:
            match = _PANEL_PORT_RE.search(line.strip())
            if match:
                panel_port = int(match.group(1))
            break

    return ChildHandle(
        pid=proc.pid,
        kind="plc",
        unit_index=unit_index,
        cmdline=cmdline_str,
        address=f"http://127.0.0.1:{panel_port}/" if panel_port else None,
    )


def _spawn_middleware(unit_index: int) -> ChildHandle:
    """Spawn a middleware process for one unit, inheriting GRAPHDB_* from the launcher."""
    cmdline = [
        sys.executable,
        "-m",
        "demo.transferunits.middleware",
        "--unit-index",
        str(unit_index),
        "--port",
        "0",
    ]
    cmdline_str = " ".join(cmdline)
    print(cmdline_str, flush=True)

    proc = subprocess.Popen(
        cmdline,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )

    return ChildHandle(pid=proc.pid, kind="middleware", unit_index=unit_index, cmdline=cmdline_str)


def _spawn_controller() -> ChildHandle:
    """Spawn the control station process, inheriting GRAPHDB_* from the launcher."""
    cmdline = [sys.executable, "-m", "demo.transferunits.control_station", "--port", "0"]
    cmdline_str = " ".join(cmdline)
    print(cmdline_str, flush=True)

    proc = subprocess.Popen(
        cmdline,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )

    return ChildHandle(pid=proc.pid, kind="controller", unit_index=None, cmdline=cmdline_str)


def _poll_service_address(db: GraphDB, resource_iri: str, timeout: float = 15.0) -> Optional[str]:
    """Poll the graph for the svc:address of the resource until it appears or the timeout expires."""
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)

    while datetime.now(timezone.utc) < deadline:
        sparql = f"""
        SELECT ?addr WHERE {{
            ?svc <https://w3id.org/circularfactory/Service#isServiceOf> <{resource_iri}> .
            ?svc <https://w3id.org/circularfactory/Service#address> ?addr .
        }}
        """
        result = db.query(sparql, convert_bindings=True)
        bindings = (
            result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
        )
        if bindings:
            return str(bindings[0]["addr"])
        time.sleep(0.5)

    return None


def probe_and_seed(units: int, force: bool = False) -> None:
    """Probe for a live factory and seed if the graph is clear, or if you force it.

    Args:
        units: Number of units to seed.
        force: Clear and seed even if a live factory exists.

    Raises:
        RuntimeError: A live factory exists, and force is False.
    """
    db = GraphDB.from_env()
    live_services = seed.factory_is_live(db)

    if live_services and not force:
        raise RuntimeError(
            f"A live factory is running: {len(live_services)} service(s) carry a fresh "
            "heartbeat. Pass --force to clear it anyway."
        )

    from kapps_ogm import OGM

    ogm = OGM(db=db)
    seed.seed_factory(db, ogm, units)
    print(f"Seeded factory with {units} unit(s).", flush=True)


def _wait_for_exit(pids: List[int], timeout: float) -> List[int]:
    """Poll every pid until it exits or the timeout runs out. Returns the pids still alive."""
    deadline = time.time() + timeout
    pending = set(pids)

    while pending and time.time() < deadline:
        for pid in list(pending):
            try:
                reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
                if reaped_pid == pid:
                    pending.discard(pid)
            except ChildProcessError:
                pending.discard(pid)
        if pending:
            time.sleep(0.1)

    return list(pending)


def _terminate_and_wait(handles: List[ChildHandle], timeout: float) -> List[str]:
    """SIGTERM every handle, wait up to timeout, then SIGKILL and report stragglers."""
    for h in handles:
        try:
            os.kill(h.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue

    still_alive = _wait_for_exit([h.pid for h in handles], timeout)

    stragglers = []
    for h in handles:
        if h.pid in still_alive:
            try:
                os.kill(h.pid, signal.SIGKILL)
                os.waitpid(h.pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            stragglers.append(f"{h.kind}[unit={h.unit_index}]" if h.unit_index else h.kind)
    return stragglers


def stop_factory(children: List[ChildHandle], timeout: float = 5.0) -> None:
    """Stop every child, middleware and the control station first, then the PLCs."""
    graph_children = [c for c in children if c.kind in ("middleware", "controller")]
    plc_children = [c for c in children if c.kind == "plc"]

    stragglers = _terminate_and_wait(graph_children, timeout)
    stragglers.extend(_terminate_and_wait(plc_children, timeout))

    if stragglers:
        print(f"Killed, past their timeout: {', '.join(stragglers)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="TransferUnit factory launcher")
    parser.add_argument("--units", type=int, default=2, help="Number of TransferUnits (default: 2)")
    parser.add_argument(
        "--force", action="store_true", help="Clear the graph even if a live factory runs"
    )
    args = parser.parse_args()

    probe_and_seed(args.units, force=args.force)
    broker_proc = _start_broker()
    children: List[ChildHandle] = []

    try:
        for n in range(1, args.units + 1):
            children.append(_spawn_plc(n))
            children.append(_spawn_middleware(n))
        children.append(_spawn_controller())

        db = GraphDB.from_env()
        for child in children:
            if child.kind == "middleware":
                resource_iri = str(seed._mint_transfer_unit_iri(child.unit_index))
            elif child.kind == "controller":
                resource_iri = str(seed.CONTROL_STATION)
            else:
                continue
            address = _poll_service_address(db, resource_iri)
            if address:
                child.address = address
                label = f"unit {child.unit_index}" if child.unit_index else "control station"
                print(f"  {child.kind} ({label}) registered at {address}", flush=True)

        print("\nFactory running. Press Ctrl+C to stop.", flush=True)

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        # Each spawn occurs inside this try block. A Ctrl+C during seeding,
        # spawning, or address polling reaches this teardown. This includes
        # a Ctrl+C during the final wait.
        print("\nStopping factory...", flush=True)
        stop_factory(children)
        if broker_proc is not None:
            broker_proc.terminate()
            try:
                broker_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                broker_proc.kill()


if __name__ == "__main__":
    main()
