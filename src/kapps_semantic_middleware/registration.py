"""Graph-write core of the KAPPS Semantic Middleware.

Every knowledge-graph **write** goes through the OGM (`OGM.create` / `OGM.commit`),
which is the architecture's single validated write path (paper §4.4.2). No write
issues raw SPARQL UPDATE. **Reads** may use the triple-store access module
(`ogm.db`) directly, which the architecture permits.

Only one direction of each inverse relation is materialized — the direction owned
by the newly-created instance (e.g. a workflow's ``svc:isWorkflowOf``, a
capability's ``svc:realizedByWorkflow``). The container-side inverses
(``svc:hasWorkflow`` etc.) are OWL-inferable and are intentionally not written, so
that each registration is a clean single-instance ``OGM.create`` rather than a
read-modify-write append onto a growing multi-valued property. Queries in this
module therefore use the materialized (instance-owned) direction.

See ADR 0002 (Operation resolves via Capability), ADR 0003 (ontology-as-ground-
truth), ADR 0004 (endpoint on Service and Workflow), ADR 0006 (OGM write path),
ADR 0009 (liveness).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, Tuple

from graph_db_interface import IRI
from kapps_ogm.utils.class_scope import ClassScope

from kapps_semantic_middleware.vocabulary import CFC, SVC

if TYPE_CHECKING:
    from kapps_ogm import OGM


class OntologyGroundTruthError(Exception):
    """A referenced class does not pre-exist as the required kind (ADR 0003)."""


class OperationResolutionError(Exception):
    """An Operation cannot be resolved to a reachable Workflow endpoint (ADR 0002)."""


# --------------------------------------------------------------------------- #
# Deterministic IRI minting (so a restarting resource reuses its IRIs).
# --------------------------------------------------------------------------- #


def mint_service_iri(resource_iri: IRI) -> IRI:
    """Mint the deterministic Service IRI for a resource: ``{resource_iri}_service``."""
    return IRI(f"{resource_iri}_service")


def mint_workflow_iri(service_iri: IRI, name: str) -> IRI:
    """Mint the deterministic Workflow IRI: ``{service_iri}_workflow_{name}``."""
    return IRI(f"{service_iri}_workflow_{name}")


def mint_capability_iri(resource_iri: IRI, name: str) -> IRI:
    """Mint the deterministic Capability IRI: ``{resource_iri}_capability_{name}``."""
    return IRI(f"{resource_iri}_capability_{name}")


def mint_state_property_iri(service_iri: IRI, name: str) -> IRI:
    """Mint the deterministic StateProperty IRI: ``{service_iri}_state_{name}``."""
    return IRI(f"{service_iri}_state_{name}")


def build_workflow_endpoint(address: str, workflow_name: str) -> str:
    """Build the callable endpoint URL for a workflow (``POST /workflows/{name}/execute``)."""
    return f"{address.rstrip('/')}/workflows/{workflow_name}/execute"


def build_state_endpoint(address: str, state_name: str) -> str:
    """Build the GET endpoint URL for a state property (``GET /state/{name}``)."""
    return f"{address.rstrip('/')}/state/{state_name}"


# --------------------------------------------------------------------------- #
# Ground-truth assertion and OGM write helpers.
# --------------------------------------------------------------------------- #


def assert_class_registered(
    ogm: "OGM", class_iri: IRI, base_iri: IRI, named_graph: Optional[IRI] = None
) -> None:
    """Assert a class pre-exists as the required kind (ADR 0003).

    Valid iff ``class_iri == base_iri`` or ``class_iri`` is a subclass of
    ``base_iri``. A read against the access module; a non-existent class makes the
    subclass check False, so this also catches a missing class.

    Raises:
        OntologyGroundTruthError: If the class is missing or not the required subclass.
    """
    if class_iri != base_iri and not ogm.db.is_subclass(
        class_iri, base_iri, named_graph=named_graph
    ):
        raise OntologyGroundTruthError(
            f"Class {class_iri} must be {base_iri} or a subclass thereof, "
            "but it is not registered as such in the knowledge graph. "
            "Types are ontology-ground-truth (ADR 0003): author the class first."
        )


def _ref(iri: IRI) -> dict:
    """Wrap an IRI as an object-property reference for OGM write data.

    Object-property values must be node references (the OGM materializes them as
    nested nodes), not literals; a ``{"id": iri}`` dict is turned into a reference
    node by the OGM's data formatter. Literals are passed as plain values.
    """
    return {"id": str(iri)}


def _create(
    ogm: "OGM",
    class_iri: IRI,
    instance_iri: IRI,
    data: dict,
    named_graph: Optional[IRI] = None,
) -> None:
    """Create a typed individual with its instance-owned properties via the OGM.

    ``data`` maps property-IRI strings to lists of values (object references as
    IRI strings, literals as their Python/str value). Idempotent for unchanged
    structure (RDF set semantics on the OGM's underlying add).
    """
    scope = ClassScope.from_property_chains([[IRI(prop)] for prop in data])
    ogm.create(
        class_iri=class_iri,
        instance_iri=instance_iri,
        data=data,
        class_scope=scope,
        persist=True,
        named_graph=named_graph,
    )


def _set(
    ogm: "OGM",
    instance_iri: IRI,
    data: dict,
    named_graph: Optional[IRI] = None,
) -> None:
    """Set/replace/remove mutable properties on an existing individual via OGM.commit.

    A value of ``[]`` removes the property. The commit is a single atomic
    DELETE/INSERT transaction, so cardinality-constrained properties are never
    transiently absent (SHACL-safe).
    """
    ogm.commit(instance_iri=instance_iri, data=data, named_graph=named_graph)


# --------------------------------------------------------------------------- #
# Registration (writes via OGM).
# --------------------------------------------------------------------------- #


def register_service(
    ogm: "OGM",
    *,
    resource_iri: IRI,
    service_iri: IRI,
    service_class: IRI,
    address: str,
    named_graph: Optional[IRI] = None,
) -> None:
    """Register a Service instance for a resource and set its base address.

    Raises OntologyGroundTruthError if ``service_class`` is not ``svc:Service`` or a
    subclass.
    """
    assert_class_registered(ogm, service_class, SVC.Service, named_graph)
    _create(
        ogm, service_class, service_iri, {str(SVC.isServiceOf): [_ref(resource_iri)]}, named_graph
    )
    _set(ogm, service_iri, {str(SVC.address): [str(address)]}, named_graph)


def register_workflow(
    ogm: "OGM",
    *,
    resource_iri: IRI,
    service_iri: IRI,
    workflow_iri: IRI,
    workflow_class: IRI,
    capability_iri: IRI,
    capability_class: IRI,
    endpoint: str,
    named_graph: Optional[IRI] = None,
) -> None:
    """Register a Workflow instance, its Capability instance, and their links.

    The Workflow owns ``svc:isWorkflowOf`` (-> service) and ``svc:endpoint``; the
    Capability owns ``svc:realizedByWorkflow`` (-> workflow). Raises
    OntologyGroundTruthError if the classes are not the required subclasses.
    """
    assert_class_registered(ogm, workflow_class, SVC.Workflow, named_graph)
    assert_class_registered(ogm, capability_class, CFC.Capability, named_graph)

    _create(
        ogm, workflow_class, workflow_iri, {str(SVC.isWorkflowOf): [_ref(service_iri)]}, named_graph
    )
    _set(ogm, workflow_iri, {str(SVC.endpoint): [str(endpoint)]}, named_graph)
    _create(
        ogm,
        capability_class,
        capability_iri,
        {str(SVC.realizedByWorkflow): [_ref(workflow_iri)]},
        named_graph,
    )


def register_state_property(
    ogm: "OGM",
    *,
    resource_iri: IRI,
    service_iri: IRI,
    state_property_iri: IRI,
    state_property_class: IRI,
    capability_iri: IRI,
    capability_class: IRI,
    endpoint: str,
    named_graph: Optional[IRI] = None,
) -> None:
    """Register a StateProperty instance, its Capability instance, and their links.

    The StateProperty owns ``svc:isStatePropertyOf`` (-> service) and
    ``svc:endpoint``; the Capability owns ``svc:providedByStateProperty`` (-> state
    property). Only the stable endpoint is written — the live value is never
    persisted.
    """
    assert_class_registered(ogm, state_property_class, SVC.StateProperty, named_graph)
    assert_class_registered(ogm, capability_class, CFC.Capability, named_graph)

    _create(
        ogm,
        state_property_class,
        state_property_iri,
        {str(SVC.isStatePropertyOf): [_ref(service_iri)]},
        named_graph,
    )
    _set(ogm, state_property_iri, {str(SVC.endpoint): [str(endpoint)]}, named_graph)
    _create(
        ogm,
        capability_class,
        capability_iri,
        {str(SVC.providedByStateProperty): [_ref(state_property_iri)]},
        named_graph,
    )


# --------------------------------------------------------------------------- #
# Deregistration (remove reachability via OGM; find targets via reads).
# --------------------------------------------------------------------------- #


def deregister_service(
    ogm: "OGM", service_iri: IRI, named_graph: Optional[IRI] = None
) -> None:
    """Remove a Service's reachability (address + all workflow/state endpoints).

    Endpoints are removed via ``OGM.commit`` (the validated write path); the
    workflows/state-properties to clear are found via a read on the instance-owned
    inverse (``svc:isWorkflowOf`` / ``svc:isStatePropertyOf``). Structural triples
    and rdf:type are preserved (paper: availability vs. existence).
    """
    db = ogm.db
    _set(ogm, service_iri, {str(SVC.address): []}, named_graph)

    for wf_iri, _, _ in db.triples_get(
        pred=SVC.isWorkflowOf, obj=service_iri, named_graph=named_graph
    ):
        _set(ogm, wf_iri, {str(SVC.endpoint): []}, named_graph)

    for sp_iri, _, _ in db.triples_get(
        pred=SVC.isStatePropertyOf, obj=service_iri, named_graph=named_graph
    ):
        _set(ogm, sp_iri, {str(SVC.endpoint): []}, named_graph)


# --------------------------------------------------------------------------- #
# Resolution + provenance.
# --------------------------------------------------------------------------- #


def resolve_operation_endpoint(ogm: "OGM", operation_iri: IRI) -> Tuple[IRI, str]:
    """Resolve an Operation to an invokable Workflow endpoint (ADR 0002).

    Chain: ``Operation --cfc:implementsCapability--> Capability
    --svc:realizedByWorkflow--> Workflow --svc:endpoint--> url``. A read against the
    access module; an unreachable (deregistered) workflow has no ``svc:endpoint`` and
    will not match.

    Raises:
        OperationResolutionError: If no online workflow realizes the capability.
    """
    sparql = f"""
    SELECT ?wf ?url WHERE {{
        <{operation_iri}> <{CFC.implementsCapability}> ?cap .
        ?cap <{SVC.realizedByWorkflow}> ?wf .
        ?wf <{SVC.endpoint}> ?url .
    }}
    """
    result = ogm.db.query(sparql, convert_bindings=True)
    bindings = (
        result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
    )
    if not bindings:
        raise OperationResolutionError(
            f"Operation {operation_iri} cannot be resolved to any online Workflow "
            "(no capability realized by a workflow with a current endpoint)."
        )
    binding = bindings[0]
    return IRI(str(binding["wf"])), str(binding["url"])


def record_operation_outcome(
    ogm: "OGM",
    *,
    operation_iri: IRI,
    workflow_iri: IRI,
    success: bool,
    result: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    named_graph: Optional[IRI] = None,
) -> None:
    """Record execution provenance on an Operation via OGM.commit (R12 writeback)."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    data: dict = {
        str(SVC.executedByWorkflow): [_ref(workflow_iri)],
        str(SVC.executionSuccess): [bool(success)],
        str(SVC.executionTimestamp): [timestamp.isoformat()],
    }
    if result is not None:
        data[str(SVC.executionResult)] = [str(result)]
    _set(ogm, operation_iri, data, named_graph)


# --------------------------------------------------------------------------- #
# Liveness: heartbeat (per-service) and watchdog sweep (centralized). ADR 0009.
# --------------------------------------------------------------------------- #


def update_heartbeat(
    ogm: "OGM",
    service_iri: IRI,
    timestamp: Optional[datetime] = None,
    named_graph: Optional[IRI] = None,
) -> None:
    """Refresh a Service's ``svc:lastHeartbeat`` via OGM.commit (atomic replace)."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    _set(ogm, service_iri, {str(SVC.lastHeartbeat): [timestamp.isoformat()]}, named_graph)


def find_stale_services(
    ogm: "OGM",
    max_age_seconds: float,
    *,
    now: Optional[datetime] = None,
    named_graph: Optional[IRI] = None,
) -> list[IRI]:
    """Find reachable-but-silent Services whose heartbeat has gone stale (a read).

    A service is stale if it currently has an ``svc:address`` but either has no
    ``svc:lastHeartbeat`` or its latest heartbeat is older than ``max_age_seconds``.
    Services are identified by ``svc:address`` presence (real services are subclass-
    typed, so ``rdf:type svc:Service`` would not match).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(seconds=max_age_seconds)).isoformat()
    sparql = f"""
    SELECT DISTINCT ?s WHERE {{
        ?s <{SVC.address}> ?addr .
        OPTIONAL {{ ?s <{SVC.lastHeartbeat}> ?hb . }}
        FILTER ( !bound(?hb) || ?hb < "{cutoff_iso}"^^<http://www.w3.org/2001/XMLSchema#dateTime> )
    }}
    """
    result = ogm.db.query(sparql, convert_bindings=True)
    bindings = (
        result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
    )
    return [IRI(str(b["s"])) for b in bindings]


def sweep_stale_services(
    ogm: "OGM",
    max_age_seconds: float,
    *,
    now: Optional[datetime] = None,
    named_graph: Optional[IRI] = None,
) -> list[IRI]:
    """Deregister every stale Service (ADR 0009 watchdog sweep). Returns swept IRIs."""
    stale = find_stale_services(ogm, max_age_seconds, now=now, named_graph=named_graph)
    for service_iri in stale:
        deregister_service(ogm, service_iri, named_graph=named_graph)
    return stale
