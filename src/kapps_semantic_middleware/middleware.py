"""KAPPS Semantic Middleware.

Extends aas_middleware.Middleware with knowledge-graph registration, discovery,
and execution capabilities. Supports three modes per ADR 0005: "resource" (wraps
one resource_iri with REST-facing workflows), "server" (reserved for data-serving
with no physical resource), and "watchdog" (reserved for liveness-sweeping).

Operation execution follows ADR 0002: an Operation resolves via its implemented
Capability to a Workflow endpoint, which is then invoked over HTTP.
"""

from __future__ import annotations

import functools
from typing import Any, Dict, Optional

import anyio
import httpx
from graph_db_interface import IRI

from aas_middleware import Middleware

from kapps_semantic_middleware.registration import (
    OperationResolutionError,
    build_workflow_endpoint,
    deregister_service,
    mint_capability_iri,
    mint_service_iri,
    mint_workflow_iri,
    record_operation_outcome,
    register_service,
    register_workflow,
    resolve_operation_endpoint,
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

        elif mode in ("server", "watchdog"):
            self.resource_iri = None
            self.service_class = None
            self.service_iri = None
            raise NotImplementedError(f"mode {mode!r} is not implemented yet")

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
