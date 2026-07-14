"""KAPPS Semantic Middleware.

Extends aas_middleware.Middleware with knowledge-graph registration, discovery,
and execution capabilities. Supports three modes per ADR 0005: "resource" (wraps
one resource_iri with REST-facing workflows), "server" (reserved for data-serving
with no physical resource), and "watchdog" (reserved for liveness-sweeping).

Operation execution follows ADR 0002: an Operation resolves via its implemented
Capability to a Workflow endpoint, which is then invoked over HTTP.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from typing import Any, Dict, List, Optional

import anyio
import httpx
from fastapi import APIRouter
from graph_db_interface import IRI

from aas_middleware import Middleware

from kapps_semantic_middleware.registration import (
    OperationResolutionError,
    build_state_endpoint,
    build_workflow_endpoint,
    deregister_service,
    mint_capability_iri,
    mint_service_iri,
    mint_state_property_iri,
    mint_workflow_iri,
    record_operation_outcome,
    register_service,
    register_state_property,
    register_workflow,
    resolve_operation_endpoint,
    sweep_stale_services,
    update_heartbeat,
)

__all__ = ["SemanticMiddleware", "OperationResolutionError"]


class SemanticMiddleware(Middleware):
    """KAPPS Semantic Middleware extending aas_middleware.Middleware.

    Adds knowledge-graph registration, discovery, and execution. Supports three
    modes per ADR 0005: "resource" (wraps one resource_iri with REST-facing
    workflows), "server" (reserved, data-serving with no physical resource), and
    "watchdog" (reserved, liveness-sweeping). Resource mode registers the
    Service/Workflow/Capability instances on startup and deregisters them on
    shutdown.

    Operation execution follows ADR 0002: an Operation resolves via its implemented
    Capability to a Workflow endpoint, which is then invoked over HTTP.
    """

    def __init__(
        self,
        *,
        mode: str = "resource",
        resource_iri: Optional[str] = None,
        service_class: Optional[str] = None,
        ogm: Any = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        address: Optional[str] = None,
        named_graph: Optional[str] = None,
        heartbeat_interval: Optional[float] = 30.0,
        staleness_threshold: float = 90.0,
        sweep_interval: float = 30.0,
    ) -> None:
        super().__init__()

        if mode not in ("resource", "server", "watchdog"):
            raise ValueError(
                f"mode must be one of 'resource', 'server', 'watchdog'; got {mode!r}"
            )

        self.mode = mode
        self.ogm = ogm
        self.host = host
        self.port = port
        self.named_graph = named_graph
        self.address = address or f"http://{host}:{port}"

        # Liveness (ADR 0009).
        self.heartbeat_interval = heartbeat_interval
        self.staleness_threshold = staleness_threshold
        self.sweep_interval = sweep_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._sweep_task: Optional[asyncio.Task] = None

        if mode == "resource":
            missing = []
            if resource_iri is None:
                missing.append("resource_iri")
            if service_class is None:
                missing.append("service_class")
            if ogm is None:
                missing.append("ogm")
            if missing:
                raise ValueError(f"resource mode requires: {', '.join(missing)}")

            self.resource_iri = IRI(resource_iri)
            self.service_class = IRI(service_class)
            self.service_iri = mint_service_iri(self.resource_iri)

            self.add_callback("on_start_up", self._register_service)
            self.add_callback("on_shutdown", self._deregister_service)
            if heartbeat_interval and heartbeat_interval > 0:
                self.add_callback("on_start_up", self._start_heartbeat)
                self.add_callback("on_shutdown", self._stop_heartbeat)

        elif mode == "watchdog":
            if ogm is None:
                raise ValueError("watchdog mode requires: ogm")
            self.resource_iri = None
            self.service_class = None
            self.service_iri = None
            self.add_callback("on_start_up", self._start_sweep)
            self.add_callback("on_shutdown", self._stop_sweep)

        elif mode == "server":
            self.resource_iri = None
            self.service_class = None
            self.service_iri = None
            raise NotImplementedError("mode 'server' is not implemented yet")

    async def _register_service(self) -> None:
        """Register the Service instance in the knowledge graph on startup."""
        await anyio.to_thread.run_sync(
            functools.partial(
                register_service,
                self.ogm.db,
                resource_iri=self.resource_iri,
                service_iri=self.service_iri,
                service_class=self.service_class,
                address=self.address,
                named_graph=self.named_graph,
            )
        )

    async def _deregister_service(self) -> None:
        """Deregister the Service instance (remove reachability) on shutdown."""
        await anyio.to_thread.run_sync(
            functools.partial(
                deregister_service,
                self.ogm.db,
                self.service_iri,
                named_graph=self.named_graph,
            )
        )

    # --- Liveness: per-service heartbeat (resource mode), ADR 0009 --------- #

    async def _start_heartbeat(self) -> None:
        """Start the background heartbeat loop (resource mode)."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Refresh svc:lastHeartbeat every ``heartbeat_interval`` seconds until cancelled."""
        # The loop is only started when a positive interval was configured.
        interval = self.heartbeat_interval or 30.0
        try:
            while True:
                await anyio.to_thread.run_sync(
                    functools.partial(
                        update_heartbeat,
                        self.ogm.db,
                        self.service_iri,
                        named_graph=self.named_graph,
                    )
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _stop_heartbeat(self) -> None:
        """Cancel the heartbeat loop on shutdown."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def emit_heartbeat(self) -> None:
        """Refresh this service's heartbeat once (also useful for tests/manual pings)."""
        await anyio.to_thread.run_sync(
            functools.partial(
                update_heartbeat, self.ogm.db, self.service_iri, named_graph=self.named_graph
            )
        )

    # --- Liveness: centralized watchdog sweep (watchdog mode), ADR 0009 ---- #

    async def _start_sweep(self) -> None:
        """Start the background staleness-sweep loop (watchdog mode)."""
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    async def _sweep_loop(self) -> None:
        """Sweep stale services every ``sweep_interval`` seconds until cancelled."""
        try:
            while True:
                await self.sweep()
                await asyncio.sleep(self.sweep_interval)
        except asyncio.CancelledError:
            pass

    async def _stop_sweep(self) -> None:
        """Cancel the sweep loop on shutdown."""
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass

    async def sweep(self) -> List[str]:
        """Deregister every stale service once; returns the swept service IRIs (as str).

        A watchdog-mode instance calls this on its ``sweep_interval``; it is also a
        plain method so a test or operator can trigger a sweep directly.
        """
        swept = await anyio.to_thread.run_sync(
            functools.partial(
                sweep_stale_services,
                self.ogm.db,
                self.staleness_threshold,
                named_graph=self.named_graph,
            )
        )
        return [str(s) for s in swept]

    def workflow(
        self,
        *args,
        capability_class: Any = None,
        workflow_class: Any = None,
        **kwargs,
    ):
        """Register a function as a REST-invokable workflow with KG registration.

        In resource mode, requires ``capability_class`` and ``workflow_class`` as
        keyword-only IRIs (both classes must pre-exist per ADR 0003). Registers the
        REST endpoint via the base class, then schedules KG registration of the
        Workflow and Capability instances on startup (after the service is
        registered).

        Raises:
            RuntimeError: If called outside resource mode.
            ValueError: If capability_class or workflow_class is missing.
        """
        if self.mode != "resource":
            raise RuntimeError(
                f"@workflow decorator only valid in resource mode; current mode is {self.mode!r}"
            )
        if capability_class is None:
            raise ValueError("capability_class is required in resource mode")
        if workflow_class is None:
            raise ValueError("workflow_class is required in resource mode")

        capability_class_iri = IRI(capability_class)
        workflow_class_iri = IRI(workflow_class)

        base_decorator = super().workflow(*args, **kwargs)

        def decorator(func):
            wrapped = base_decorator(func)
            name = func.__name__
            workflow_iri = mint_workflow_iri(self.service_iri, name)
            capability_iri = mint_capability_iri(self.resource_iri, name)
            endpoint = build_workflow_endpoint(self.address, name)

            async def register_workflow_callback() -> None:
                await anyio.to_thread.run_sync(
                    functools.partial(
                        register_workflow,
                        self.ogm.db,
                        resource_iri=self.resource_iri,
                        service_iri=self.service_iri,
                        workflow_iri=workflow_iri,
                        workflow_class=workflow_class_iri,
                        capability_iri=capability_iri,
                        capability_class=capability_class_iri,
                        endpoint=endpoint,
                        named_graph=self.named_graph,
                    )
                )

            self.add_callback("on_start_up", register_workflow_callback)
            return wrapped

        return decorator

    def state(
        self,
        *,
        capability_class: Any = None,
        state_property_class: Any = None,
        name: Optional[str] = None,
    ):
        """Expose a getter as a GET-readable state property with KG registration.

        Parallel to :meth:`workflow` but GET-only, for a readable, potentially
        high-frequency-changing value (e.g. a door's status). In resource mode,
        requires ``capability_class`` and ``state_property_class`` as keyword-only
        IRIs (both classes must pre-exist per ADR 0003). Registers a GET endpoint at
        ``/state/{name}`` that calls the decorated getter on demand — the live value
        is NEVER written to the graph; only the stable endpoint triple is, at
        registration.

        Raises:
            RuntimeError: If called outside resource mode.
            ValueError: If capability_class or state_property_class is missing.
        """
        if self.mode != "resource":
            raise RuntimeError(
                f"@state decorator only valid in resource mode; current mode is {self.mode!r}"
            )
        if capability_class is None:
            raise ValueError("capability_class is required in resource mode")
        if state_property_class is None:
            raise ValueError("state_property_class is required in resource mode")

        capability_class_iri = IRI(capability_class)
        state_property_class_iri = IRI(state_property_class)

        def decorator(func):
            state_name = name or func.__name__
            state_property_iri = mint_state_property_iri(self.service_iri, state_name)
            capability_iri = mint_capability_iri(self.resource_iri, state_name)
            endpoint = build_state_endpoint(self.address, state_name)

            router = APIRouter(prefix=f"/state/{state_name}", tags=["state"])

            @router.get("")
            async def get_state():
                result = func()
                if inspect.isawaitable(result):
                    result = await result
                return result

            self.app.include_router(router)

            async def register_state_property_callback() -> None:
                await anyio.to_thread.run_sync(
                    functools.partial(
                        register_state_property,
                        self.ogm.db,
                        resource_iri=self.resource_iri,
                        service_iri=self.service_iri,
                        state_property_iri=state_property_iri,
                        state_property_class=state_property_class_iri,
                        capability_iri=capability_iri,
                        capability_class=capability_class_iri,
                        endpoint=endpoint,
                        named_graph=self.named_graph,
                    )
                )

            self.add_callback("on_start_up", register_state_property_callback)
            return func

        return decorator

    async def execute(
        self,
        operation_iri: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an Operation by resolving it to a Workflow endpoint and invoking it.

        Follows the ADR 0002 resolution chain (Operation --implementsCapability-->
        Capability --realizedByWorkflow--> Workflow --endpoint--> URL), invokes the
        endpoint over HTTP, and records execution provenance on the Operation (R12)
        whether or not the call succeeds.

        This is a Python method only (not a REST route) per ADR 0005 resource mode.

        Args:
            operation_iri: IRI of the Operation to execute.
            payload: Optional JSON payload sent in the POST body.

        Returns:
            Dict with keys: operation, workflow, endpoint, success, result.

        Raises:
            OperationResolutionError: If no online Workflow realizes the capability.
            httpx.HTTPError: On HTTP failures (recorded as a failed outcome first).
        """
        operation_iri_obj = IRI(operation_iri)

        workflow_iri, url = await anyio.to_thread.run_sync(
            functools.partial(
                resolve_operation_endpoint,
                self.ogm.db,
                operation_iri_obj,
            )
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if payload is not None:
                    response = await client.post(url, json=payload)
                else:
                    response = await client.post(url)

                success = response.is_success
                try:
                    result = response.json()
                except Exception:
                    result = response.text

                await anyio.to_thread.run_sync(
                    functools.partial(
                        record_operation_outcome,
                        self.ogm.db,
                        operation_iri=operation_iri_obj,
                        workflow_iri=workflow_iri,
                        success=success,
                        result=str(result),
                    )
                )

                return {
                    "operation": str(operation_iri_obj),
                    "workflow": str(workflow_iri),
                    "endpoint": url,
                    "success": success,
                    "result": result,
                }

        except httpx.HTTPError as exc:
            await anyio.to_thread.run_sync(
                functools.partial(
                    record_operation_outcome,
                    self.ogm.db,
                    operation_iri=operation_iri_obj,
                    workflow_iri=workflow_iri,
                    success=False,
                    result=str(exc),
                )
            )
            raise
