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
import contextlib
import functools
import inspect
import logging
from typing import Any, Dict, List, Optional

import anyio
import httpx
from fastapi import APIRouter
from graph_db_interface import IRI
from pydantic import BaseModel

from aas_middleware import Middleware

from kapps_semantic_middleware.registration import (
    OperationQueueEmpty,
    OperationResolutionError,
    build_event_trigger_url,
    build_state_endpoint,
    build_workflow_endpoint,
    create_operation,
    deregister_service,
    mint_capability_iri,
    mint_operation_iri,
    mint_service_iri,
    mint_state_property_iri,
    mint_workflow_iri,
    record_operation_outcome,
    record_terminal_status,
    register_service,
    register_state_property,
    register_workflow,
    resolve_dispatch_target,
    resolve_operation_endpoint,
    resolve_operation_workflow,
    revert_operation,
    set_operation_status,
    sweep_stale_services,
    update_heartbeat,
)
from kapps_semantic_middleware.vocabulary import OperationStatus

logger = logging.getLogger(__name__)

__all__ = ["SemanticMiddleware", "OperationResolutionError"]


class _EventTriggerPayload(BaseModel):
    """REST body of the event trigger: the IRI of the Operation now in the graph (ADR 0009)."""

    operation_iri: str


class _OperationDraft:
    """Mutable draft yielded by ``request(...)``.

    The dispatch body populates ``data`` (domain property-IRI str -> list of values) and
    can read ``iri`` (the minted Operation IRI). The atomic exit turns it into a graph
    Operation and fires the event trigger (ADR 0010).
    """

    def __init__(self, iri: IRI) -> None:
        self.iri = iri
        self.data: Dict[str, list] = {}


class _ClaimedOperation:
    """Handle yielded by ``claim_next(...)`` (ADR 0010 pull-and-run).

    ``operation`` is the re-fetched Operation (a `kapps_ogm` Node — hydrated under the
    domain-supplied ClassScope, or a bare reference when no scope was given); the body reads
    it to decide what work to do and sets ``result`` to the outcome, which is recorded as
    ``svc:executionResult`` in the terminal transition.
    """

    def __init__(self, iri: IRI, operation: Any) -> None:
        self.iri = iri
        self.operation = operation
        self.result: Optional[str] = None


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

            # Event-trigger coordination (ADR 0009/0010): an in-memory operation queue
            # (the graph is the source of truth; durability/reconstruction is #17) and the
            # receiver-side event-trigger REST route that other resources ring to dispatch.
            self._operation_queue: List[IRI] = []
            self._register_event_trigger()

            self.add_callback("on_start_up", self._register_service)
            self.add_callback("on_shutdown", self._deregister_service)
            # Stand up the resource's REST interface from graph ground truth
            # (generate_rest_interface: OGM-fetch the resource instance -> datamodel -> API).
            self.add_callback("on_start_up", self._load_resource_datamodel)
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
                self.ogm,
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
                self.ogm,
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
                        self.ogm,
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
                update_heartbeat, self.ogm, self.service_iri, named_graph=self.named_graph
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
                self.ogm,
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
                        self.ogm,
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
                        self.ogm,
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
                self.ogm,
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
                        self.ogm,
                        operation_iri=operation_iri_obj,
                        workflow_iri=workflow_iri,
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
                    self.ogm,
                    operation_iri=operation_iri_obj,
                    workflow_iri=workflow_iri,
                    result=str(exc),
                )
            )
            raise

    # ------------------------------------------------------------------ #
    # Event-trigger coordination: receiver intake + caller dispatch.
    # ADR 0009 (event-trigger model), ADR 0010 (transaction context managers).
    # NOTE: the synchronous execute() above is retained until pull-and-run (#14)
    # can run the work through the new model; it is removed in #14/#19.
    # ------------------------------------------------------------------ #

    def _register_event_trigger(self) -> None:
        """Expose the built-in ``execute`` event trigger on the REST API (ADR 0009).

        Mounted via the base aas_middleware workflow mechanism as a plain REST route
        (``POST /workflows/event_trigger/execute``) — deliberately NOT a KG-registered
        ``svc:Workflow``: the event trigger is framework plumbing every resource-mode
        instance exposes so peers can ring it, not a domain capability (ADR 0005 amended).
        """
        middleware = self

        async def event_trigger(payload: _EventTriggerPayload) -> Dict[str, str]:
            return await middleware._handle_event_trigger(IRI(payload.operation_iri))

        # Base decorator mounts the route without the KG registration the KAPPS
        # ``self.workflow(...)`` override performs.
        Middleware.workflow(self)(event_trigger)

    async def _handle_event_trigger(self, operation_iri: IRI) -> Dict[str, str]:
        """Receiver-side event-trigger intake (ADR 0009).

        The trigger carries only the Operation IRI — its payload lives in the graph. We
        ``ogm.fetch`` the Operation (confirming it exists) and enqueue it into this
        instance's in-memory queue, leaving it ``queued`` and returning immediately with
        no business result. A domain callback (#15) / pull-and-run (#14) is what later
        runs the work; this slice only enqueues.
        """
        await anyio.to_thread.run_sync(
            functools.partial(self.ogm.fetch, instance_iri=operation_iri)
        )
        self._operation_queue.append(operation_iri)
        return {"operation": str(operation_iri), "status": OperationStatus.QUEUED}

    @contextlib.contextmanager
    def request(
        self,
        *,
        capability_class: Any,
        operation_class: Any,
        operation_iri: Optional[str] = None,
        target_resource: Optional[str] = None,
    ):
        """Caller-side dispatch as a transaction context manager (ADR 0010).

        Usage::

            with mw.request(capability_class=cap, operation_class=op_cls) as op:
                ...  # populate op.data with the operation's domain fields (if any)

        The body populates the yielded draft; on clean exit the middleware **atomically**
        creates the Operation (status ``queued``, addressed to a reachable Service via its
        Capability — ADR 0002 discovery) and triggers that Service's event trigger over
        REST. If the trigger fails to deliver, the created Operation is reverted (ADR 0010
        atomic create-and-notify). A body exception aborts before anything is written.

        This is the in-process caller face — not REST-exposed (ADR 0005/0010).
        """
        if self.mode != "resource":
            raise RuntimeError(
                f"request() is only valid in resource mode; current mode is {self.mode!r}"
            )
        capability_class_iri = IRI(capability_class)
        operation_class_iri = IRI(operation_class)
        op_iri = (
            IRI(operation_iri) if operation_iri else mint_operation_iri(operation_class_iri)
        )

        # __enter__ precondition, OUTSIDE the transaction (ADR 0010): resolve a reachable
        # receiver for the capability BEFORE the body runs, so an unroutable dispatch fails
        # before any domain work rather than at commit.
        capability_iri, _service_iri, address = resolve_dispatch_target(
            self.ogm,
            capability_class_iri,
            target_resource=IRI(target_resource) if target_resource else None,
            named_graph=self.named_graph,
        )
        draft = _OperationDraft(op_iri)

        # Body runs here; an exception propagates and nothing is written.
        yield draft

        # __exit__ (clean): atomically create the Operation and fire the event trigger.
        create_operation(
            self.ogm,
            operation_iri=op_iri,
            operation_class=operation_class_iri,
            capability_iri=capability_iri,
            status=OperationStatus.QUEUED,
            data=draft.data or None,
            named_graph=self.named_graph,
        )
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    build_event_trigger_url(address),
                    json={"operation_iri": str(op_iri)},
                )
                response.raise_for_status()
        except Exception:
            revert_operation(
                self.ogm,
                op_iri,
                operation_class=operation_class_iri,
                capability_iri=capability_iri,
                data=draft.data or None,
                named_graph=self.named_graph,
            )
            raise

    @contextlib.contextmanager
    def claim_next(self, scope: Any = None):
        """Pull-and-run the next queued Operation as a transaction context manager (ADR 0009/0010).

        Usage::

            with mw.claim_next(scope) as claimed:
                claimed.result = do_the_work(claimed.operation)

        `__enter__` pops the next `queued` Operation from this instance's in-memory queue
        (FIFO; raises `OperationQueueEmpty` if none), marks it `running`, and re-fetches it
        under the domain-supplied `ClassScope` so the body gets exactly the object shape it
        needs. The body runs the work and may set `claimed.result`. On clean exit the CM
        **atomically** records `done` + provenance (`executedByWorkflow` / `executionTimestamp`
        / `executionResult`); on a body exception it records `failed` + the exception message
        and re-raises. Provenance is folded into the terminal transition (ADR 0009); the
        resource-datamodel failure dump is deferred to a later slice.

        This is the in-process receiver face — not REST-exposed (ADR 0005/0010).
        """
        if self.mode != "resource":
            raise RuntimeError(
                f"claim_next() is only valid in resource mode; current mode is {self.mode!r}"
            )
        if not self._operation_queue:
            raise OperationQueueEmpty("no queued Operation to pull")
        op_iri = self._operation_queue[0]  # peek FIFO; only dequeue once preconditions pass

        # Precondition, BEFORE any mutation (ADR 0010): resolve the Workflow for provenance
        # WITHOUT requiring a live endpoint, so `executedByWorkflow` is recorded even if the
        # workflow's `svc:endpoint` was deregistered mid-run. If this raises, the Operation
        # stays queued (in the graph and this in-memory queue) for a later retry.
        workflow_iri = resolve_operation_workflow(
            self.ogm, op_iri, named_graph=self.named_graph
        )

        # Preconditions passed — claim it: dequeue, mark running, then re-fetch under scope.
        self._operation_queue.pop(0)
        set_operation_status(
            self.ogm,
            operation_iri=op_iri,
            status=OperationStatus.RUNNING,
            named_graph=self.named_graph,
        )
        if scope is not None:
            operation = self.ogm.fetch(
                instance_iri=op_iri, class_scope=scope, materialize=True
            )
        else:
            operation = self.ogm.fetch(instance_iri=op_iri, as_reference=True)
        claimed = _ClaimedOperation(op_iri, operation)

        try:
            yield claimed
        except Exception as exc:
            record_terminal_status(
                self.ogm,
                operation_iri=op_iri,
                workflow_iri=workflow_iri,
                status=OperationStatus.FAILED,
                result=str(exc),
                named_graph=self.named_graph,
            )
            raise
        else:
            record_terminal_status(
                self.ogm,
                operation_iri=op_iri,
                workflow_iri=workflow_iri,
                status=OperationStatus.DONE,
                result=claimed.result,
                named_graph=self.named_graph,
            )

    async def _load_resource_datamodel(self) -> None:
        """Expose the resource's REST interface generated from graph ground truth (ADR 0009).

        Resource mode builds its REST surface from the graph: OGM-fetch the resource
        individual, materialize its aas_middleware datamodel, and generate the CRUD REST
        API (``generate_rest_api_for_data_model``). Best-effort and additive — the
        event-trigger and workflow routes are the load-bearing surface for this slice, so
        a resource with no materializable data is skipped with a warning rather than
        failing startup.
        """
        try:
            node = await anyio.to_thread.run_sync(
                functools.partial(
                    self.ogm.fetch, instance_iri=self.resource_iri, materialize=True
                )
            )
            instance = getattr(node, "instance", None)
            if instance is None:
                return
            self.load_model_instances("resource", [instance])
            self.generate_rest_api_for_data_model("resource")
        except Exception as exc:  # noqa: BLE001 - additive convenience surface, never fatal
            logger.warning(
                "Could not generate the resource datamodel REST API for %s: %s",
                self.resource_iri,
                exc,
            )
