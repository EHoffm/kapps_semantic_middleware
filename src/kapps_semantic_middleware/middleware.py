"""KAPPS Semantic Middleware.

Extends aas_middleware.Middleware with knowledge-graph registration, discovery,
and execution capabilities. Supports three modes per ADR 0005 -- see `modes.Mode`
for what each one means and which are implemented.

Operation execution follows ADR 0002: an Operation resolves via its implemented
Capability to a Workflow endpoint, which is then invoked over HTTP.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import json
import logging
from typing import Any, Dict, List, Optional

import anyio
import httpx
from fastapi import APIRouter
from graph_db_interface import IRI
from pydantic import BaseModel

from aas_middleware import Middleware
from aas_middleware.middleware.sync.synced_connector import SyncDirection

from kapps_semantic_middleware.connectors.semantic import (
    SemanticConnectorRegistry,
    default_registry,
)
from kapps_semantic_middleware.connectors.wiring import WiringPlan, plan_wiring
from kapps_semantic_middleware import modes
from kapps_semantic_middleware.modes import Mode
from kapps_semantic_middleware.rest_router import generate_recursive_rest_api
from kapps_semantic_middleware.registration import (
    HandoverPreconditionError,
    OperationQueueEmpty,
    OperationResolutionError,
    build_event_trigger_url,
    build_state_endpoint,
    build_workflow_endpoint,
    counterpart_has_complementary_ability,
    create_operation,
    deregister_service,
    find_possession_state,
    find_resource_operations,
    mark_operation_failed,
    mint_capability_iri,
    mint_operation_iri,
    mint_service_iri,
    mint_state_property_iri,
    mint_workflow_iri,
    record_terminal_status,
    register_service,
    register_state_property,
    register_workflow,
    resolve_dispatch_target,
    resolve_operation_workflow,
    revert_operation,
    set_operation_status,
    switch_possession,
    sweep_stale_services,
    update_heartbeat,
)
from kapps_semantic_middleware.vocabulary import OperationStatus

logger = logging.getLogger(__name__)

__all__ = ["SemanticMiddleware", "OperationResolutionError", "Mode"]


class _EventTriggerPayload(BaseModel):
    """REST body of the event trigger: the IRI of the Operation now in the graph (ADR 0009)."""

    # `str`, not `IRI`, and deliberately so (#45). `IRI.__get_pydantic_core_schema__` returns
    # `any_schema()` — permissive by design, on the grounds that IRI validates itself — so
    # annotating this `IRI` would neither validate nor convert the incoming value: the
    # attribute would hold a plain `str` while claiming to be an `IRI`. Taking `str` at the
    # boundary and converting explicitly in `_handle_event_trigger` puts the validation where
    # a malformed IRI actually raises. The safer-looking annotation is the less safe one.
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

    Adds knowledge-graph registration, discovery, and execution. Supports the three
    modes of :class:`~kapps_semantic_middleware.modes.Mode`; resource mode registers
    the Service/Workflow/Capability instances on startup and deregisters them on
    shutdown, and is the only one with runtime consequence today.

    ``mode`` accepts a ``Mode`` constant or the equivalent bare string -- ``Mode`` is a
    ``str`` subclass, so existing ``mode="resource"`` callers are unaffected.

    Operation execution: an Operation resolves via its implemented
    Capability to a Workflow endpoint, which is then invoked over HTTP.
    """

    def __init__(
        self,
        *,
        mode: Mode = Mode.RESOURCE,
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
        class_scope: Any = None,
        autoregister_connectors: bool = True,
        connector_sync_direction: SyncDirection = SyncDirection.BIDIRECTIONAL,
        connector_registry: Optional[SemanticConnectorRegistry] = None,
    ) -> None:
        super().__init__()

        if mode not in modes.ALL:
            raise ValueError(
                f"mode must be one of {', '.join(repr(str(m)) for m in modes.ALL)}; "
                f"got {mode!r}"
            )

        self.mode = mode
        self.ogm = ogm
        self.host = host
        self.port = port
        self.named_graph = named_graph
        self.address = address or f"http://{host}:{port}"

        # Liveness.
        self.heartbeat_interval = heartbeat_interval
        self.staleness_threshold = staleness_threshold
        self.sweep_interval = sweep_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._sweep_task: Optional[asyncio.Task] = None

        if mode == Mode.RESOURCE:
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

            # Connector wiring (ADR 0022/0023/0028). The class_scope is the consumer's view,
            # rooted at this resource and configured in embedding code rather than in the
            # ontology (ADR 0018) -- a TransferUnit's parameters hang off its belts and
            # barriers, so reaching them needs a two-level chain the ontology cannot guess.
            self.class_scope = class_scope
            self.autoregister_connectors = autoregister_connectors
            self.connector_sync_direction = connector_sync_direction
            self.connector_registry = connector_registry or default_registry
            # None until a class_scope is given: without a consumer's view there is nothing
            # to root recognition at, and the datamodel fetch stays unscoped as it is for
            # scenarios 1 and 2.
            self._wiring: Optional[WiringPlan] = None
            # The parameter routes the recursive router generated, in tree order (ADR 0017).
            # Populated at startup; kept because "what did I actually expose?" is otherwise
            # answerable only by filtering `app.routes` and re-deriving which of them are
            # parameters -- and because a silently empty list is the symptom of a tree walk
            # that missed a branch.
            self._parameter_routes: List[str] = []
            if class_scope is not None:
                self._wire_semantic_connectors()

            # Event-trigger coordination (ADR 0009/0010): an in-memory operation queue
            # (the graph is the source of truth; durability/reconstruction is #17) and the
            # receiver-side event-trigger REST route that other resources ring to dispatch.
            self._operation_queue: List[IRI] = []
            # Optional domain callback fired on enqueue (#15); None = leave the Operation
            # queued for a manual claim_next. Background tasks are tracked so they are not
            # garbage-collected before they finish.
            self._callback: Optional[Any] = None
            self._callback_scope: Any = None
            self._callback_tasks: set = set()
            self._register_event_trigger()

            self.add_callback("on_start_up", self._register_service)
            self.add_callback("on_shutdown", self._deregister_service)
            # Stand up the resource's REST interface from graph ground truth
            # (generate_rest_interface: OGM-fetch the resource instance -> datamodel -> API).
            self.add_callback("on_start_up", self._load_resource_datamodel)
            # Reconstruct the operation queue from the graph (ADR 0009 durability): a one-shot
            # startup query, so no work is lost across a restart and no steady-state polling.
            self.add_callback("on_start_up", self._reconstruct_queue)
            if heartbeat_interval and heartbeat_interval > 0:
                self.add_callback("on_start_up", self._start_heartbeat)
                self.add_callback("on_shutdown", self._stop_heartbeat)

        elif mode == Mode.WATCHDOG:
            if ogm is None:
                raise ValueError("watchdog mode requires: ogm")
            self.resource_iri = None
            self.service_class = None
            self.service_iri = None
            self.add_callback("on_start_up", self._start_sweep)
            self.add_callback("on_shutdown", self._stop_sweep)

        elif mode == Mode.SERVER:
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

    # --- Liveness: per-service heartbeat (resource mode), ADR 0007 --------- #

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

    # --- Liveness: centralized watchdog sweep (watchdog mode), ADR 0007 ---- #

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
        if self.mode != Mode.RESOURCE:
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
        if self.mode != Mode.RESOURCE:
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

    # ------------------------------------------------------------------ #
    # Event-trigger coordination: receiver intake + caller dispatch.
    # ADR 0009 (event-trigger model), ADR 0010 (transaction context managers).
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
        if self._callback is not None:
            # Fire the domain callback in the background (#15): the trigger returns
            # immediately (ADR 0009 — it does not block on the work); the pull-and-run runs
            # off the event loop so its blocking graph I/O never stalls the server. Keep a
            # reference so the task is not garbage-collected before it finishes.
            task = asyncio.create_task(self._run_callback())
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)
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
        if self.mode != Mode.RESOURCE:
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
        if self.mode != Mode.RESOURCE:
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
                failure_state=self._dump_resource_datamodel(),
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

    @contextlib.contextmanager
    def handover(self, *, mode: Any, workpiece: Any, counterpart: Any):
        """Change-of-possession primitive as a transaction context manager (ADR 0011).

        Usage::

            with mw.handover(mode=MES.Pass, workpiece=wp, counterpart=other):
                ...  # domain-owned physical transport / counterpart coordination

        `__enter__` runs exactly two precondition checks OUTSIDE the transaction: (1) the caller
        currently possesses the workpiece (a `cfc:PossessionState` the workpiece points to with
        this resource as possessor), and (2) the counterpart carries the `mes:hasHandoverAbility`
        COMPLEMENTARY to `mode`. There is deliberately no destination-free / universal maxCount-1
        check — possession is not universally single. The body is domain-owned (physical
        transport and any counterpart coordination, e.g. via a `request(...)` dispatch); the core
        never references the event trigger. On clean exit `__exit__` switches possession to the
        counterpart: it appends the counterpart's `cfc:hasPossessor` to a fresh PossessionState
        (an atomic insertion — a resource may possess several workpieces) and then re-points the
        workpiece's cardinality-1 `cfc:hasPossessedWorkpiece` in a single OGM DELETE/INSERT
        (the update path, ADR 0008); the workpiece thus points to exactly one PossessionState
        throughout. On an exception it aborts with no switch. Possession is Core's reified model
        (`cfc:PossessionState`); the "possessed by exactly one" cardinality is Core's own
        Workpiece restriction, the commit-time SHACL backstop.
        """
        if self.mode != Mode.RESOURCE:
            raise RuntimeError(
                f"handover() is only valid in resource mode; current mode is {self.mode!r}"
            )
        workpiece_iri = IRI(workpiece)
        counterpart_iri = IRI(counterpart)
        mode_ability_iri = IRI(mode)

        # __enter__ preconditions, OUTSIDE the transaction (ADR 0011/0010).
        current_ps = find_possession_state(
            self.ogm, workpiece_iri, self.resource_iri, named_graph=self.named_graph
        )
        if current_ps is None:
            raise HandoverPreconditionError(
                f"{self.resource_iri} does not currently possess {workpiece_iri}"
            )
        if not counterpart_has_complementary_ability(
            self.ogm, counterpart_iri, mode_ability_iri, named_graph=self.named_graph
        ):
            raise HandoverPreconditionError(
                f"counterpart {counterpart_iri} lacks the handover ability complementary "
                f"to {mode_ability_iri}"
            )

        # Body runs here; an exception aborts before any possession switch.
        yield

        # __exit__ (clean): switch possession to the counterpart (append possessor link, then
        # atomically re-point the workpiece's single possession).
        switch_possession(
            self.ogm,
            workpiece_iri=workpiece_iri,
            new_possessor_iri=counterpart_iri,
            named_graph=self.named_graph,
        )

    def register_callback(self, callback: Any, scope: Any = None) -> None:
        """Register a domain work callback fired on enqueue (#15, ADR 0009).

        `callback` is the work function `callback(operation) -> result`: it runs the
        Operation's work and returns the value recorded as `svc:executionResult`. On each
        enqueue the middleware drives a background pull-and-run around it —
        `with claim_next(scope) as c: c.result = callback(c.operation)` — so status
        (`running`->`done`/`failed`) and provenance are handled by the middleware and the
        domain writes only the work. Opt-in: with no callback registered, an enqueued
        Operation is left `queued` for a manual `claim_next`. `scope` is the domain
        ClassScope used to re-fetch the Operation.
        """
        if self.mode != Mode.RESOURCE:
            raise RuntimeError(
                f"register_callback() is only valid in resource mode; current mode is {self.mode!r}"
            )
        self._callback = callback
        self._callback_scope = scope

    async def _run_callback(self) -> None:
        """Drive the domain callback's pull-and-run off the event loop (#15).

        The blocking pull-and-run runs in a worker thread so it never stalls the server. A
        failure inside the domain work is a normal terminal outcome — `claim_next` has
        already recorded it as `failed` with provenance in the graph — so it is logged at
        warning level (not error) here; the exception is caught only so this fire-and-forget
        task does not leak an unretrieved-exception warning. A drained-queue race
        (`OperationQueueEmpty`, another callback task claimed the op first) is benign.
        """
        try:
            await anyio.to_thread.run_sync(self._drive_callback)
        except OperationQueueEmpty:
            pass  # another callback task claimed the operation first; nothing to do
        except Exception:
            logger.warning(
                "Domain callback did not complete cleanly for a queued operation on %s",
                self.resource_iri,
                exc_info=True,
            )

    def _drive_callback(self) -> None:
        """Run one pull-and-run wrapping the registered domain callback (#15)."""
        callback = self._callback
        if callback is None:  # defensive: only scheduled when a callback is registered
            return
        with self.claim_next(self._callback_scope) as claimed:
            claimed.result = callback(claimed.operation)

    async def _reconstruct_queue(self) -> None:
        """Reconstruct the operation queue from the graph on startup (ADR 0009 durability).

        Own ``queued`` Operations are re-enqueued into the in-memory cache; own orphaned
        ``running`` Operations — this resource crashed mid-execution — are transitioned to
        ``failed`` and never auto-rerun, because a half-done physical action must not silently
        replay. Both are found by ontology traversal (Operation -> Capability <- resource),
        whose links persist across a restart, so this is a one-shot startup query rather than
        steady-state polling.
        """
        queued = await anyio.to_thread.run_sync(
            functools.partial(
                find_resource_operations,
                self.ogm,
                self.resource_iri,
                [OperationStatus.QUEUED],
                self.named_graph,
            )
        )
        for op_iri in queued:
            if op_iri not in self._operation_queue:
                self._operation_queue.append(op_iri)

        orphaned = await anyio.to_thread.run_sync(
            functools.partial(
                find_resource_operations,
                self.ogm,
                self.resource_iri,
                [OperationStatus.RUNNING],
                self.named_graph,
            )
        )
        for op_iri in orphaned:
            await anyio.to_thread.run_sync(
                functools.partial(
                    mark_operation_failed,
                    self.ogm,
                    op_iri,
                    "orphaned running operation reclaimed at startup; not auto-rerun",
                    self.named_graph,
                )
            )

    def _wire_semantic_connectors(self) -> None:
        """Recognise this resource's interface parameters and connect what the flavour allows.

        Called from ``__init__`` rather than from an ``on_start_up`` callback, and that is
        not a stylistic choice: ``lifespan`` calls ``connect()`` on everything in the
        connection registry *before* running ``on_start_up``, and ``initiate_sync`` — what
        ``add_synced_connector`` defers — starts ``run_receive()`` but never calls
        ``connect()``. A connector registered later never connects, its listener never
        starts, and ``receive()`` blocks forever while outbound limps on through
        ``consume()``'s reconnect. Silent, one-directional failure (ADR 0023).

        Recognition and the northbound projection run whatever the flavour;
        ``autoregister_connectors`` gates only the connecting. An inspector that skipped
        recognition would treat each parameter node as ordinary data and serve its broker
        address northbound — the least-privileged instance would leak the most (ADR 0028).
        """
        # Deliberately not wrapped in a try/except. Asking for a class_scope is asking for the
        # parameters under it to be wired, and a resource that cannot resolve them has not
        # "come up with a smaller surface" — it has come up unable to reach its device, with
        # the projection that keeps broker addresses off the wire never having been computed.
        # Failing construction is the honest outcome; a warning here would produce exactly
        # the silent half-alive resource ADR 0023 is written to avoid.
        self._wiring = plan_wiring(
            ogm=self.ogm,
            resource_iri=self.resource_iri,
            class_scope=self.class_scope,
            registry=self.connector_registry,
            flavour=self.connector_sync_direction,
            autoregister=self.autoregister_connectors,
        )

        for binding, registration in self._wiring.registrations:
            self.add_synced_connector(
                connector_id=f"{binding.resource_iri}#{binding.field_id}#{registration.suffix}",
                connector=registration.connector,
                model_type=registration.model_type,
                data_model_name="resource",
                model_id=str(self.resource_iri),
                # The COMPLEX property is the deepest addressable thing: ConnectionInfo has
                # three levels and field_id is a plain getattr, so inf:hasValue is out of
                # reach. Same atomic unit ADR 0017 reached from the routing side.
                contained_model_id=str(binding.resource_iri),
                field_id=binding.field_id,
                formatter=registration.formatter,
                sync_role=registration.sync_role,
                sync_direction=registration.sync_direction,
            )

        if self._wiring.registrations:
            logger.info(
                "Wired %d connector(s) across %d parameter(s) on %s",
                len(self._wiring.registrations),
                len(self._wiring.bindings),
                self.resource_iri,
            )

    async def _load_resource_datamodel(self) -> None:
        """Expose the resource's REST interface generated from graph ground truth (ADR 0009).

        Resource mode builds its REST surface from the graph: OGM-fetch the resource
        individual, materialize its aas_middleware datamodel, and generate the CRUD REST
        API (``generate_rest_api_for_data_model``). Best-effort and additive — the
        event-trigger and workflow routes are the load-bearing surface for this slice, so
        a resource with no materializable data is skipped with a warning rather than
        failing startup.

        When a ``class_scope`` was given, the fetch goes through the **pruned** spec, so the
        served datamodel has no field that could carry a broker address or a topic
        (ADR 0028). Without one, the fetch is unscoped and returns the bare individual —
        which is what scenarios 1 and 2 rely on and why the projection cannot leak there.
        """
        try:
            fetch = functools.partial(
                self.ogm.fetch, instance_iri=self.resource_iri, materialize=True
            )
            if self._wiring is not None:
                fetch = functools.partial(
                    self.ogm.fetch,
                    instance_iri=self.resource_iri,
                    **self._wiring.northbound_fetch_kwargs(),
                )
            node = await anyio.to_thread.run_sync(fetch)
            instance = getattr(node, "instance", None)
            if instance is None:
                return
            self.load_model_instances("resource", [instance])
            # The local recursive router, not the framework generator (ADR 0017). It still
            # produces the framework's top-level CRUD -- it calls it -- and then descends the
            # datamodel tree to give every interface-accessible parameter its own address, so a
            # setpoint is a PUT to one belt rather than a read-modify-write of the whole list.
            # With no wiring there are no bindings, so nothing is added and scenarios 1 and 2
            # keep exactly the surface they have today.
            self._parameter_routes = generate_recursive_rest_api(
                self,
                "resource",
                root_id=str(self.resource_iri),
                instance=instance,
                bindings=self._wiring.bindings if self._wiring is not None else (),
            )
        except Exception as exc:  # noqa: BLE001 - additive convenience surface, never fatal
            logger.warning(
                "Could not generate the resource datamodel REST API for %s: %s",
                self.resource_iri,
                exc,
            )

    def _dump_resource_datamodel(self) -> Optional[str]:
        """Serialize this resource's aas_middleware datamodel to a JSON string, or None.

        The failed-Operation state snapshot (ADR 0009 / #14): on a body exception, `claim_next`
        records this alongside `operationStatus=failed` (`svc:failureState`) so the resource
        state under which the failure occurred is diagnosable from the graph. Best-effort — a
        resource with no materializable datamodel, or a serialization error, yields None so the
        `failed` status and error string are still recorded; the snapshot is purely additive.
        """
        try:
            node = self.ogm.fetch(instance_iri=self.resource_iri, materialize=True)
            instance = getattr(node, "instance", None)
            if instance is None:
                return None
            if isinstance(instance, BaseModel):
                return instance.model_dump_json()
            return json.dumps(instance, default=str)
        except Exception as exc:  # noqa: BLE001 - additive diagnostic, never fatal to failure recording
            logger.warning(
                "Could not serialize resource datamodel for failure dump of %s: %s",
                self.resource_iri,
                exc,
            )
            return None
