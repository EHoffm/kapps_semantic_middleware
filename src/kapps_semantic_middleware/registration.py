"""Graph-write core of the KAPPS Semantic Middleware.

Creates the RDF individuals a middleware instance needs at startup, removes their
reachability triples at shutdown, resolves an Operation to an invokable Workflow
endpoint, and records execution outcomes. All writes are idempotent (safe to call
again on restart).

This module writes structural and provenance triples directly via
`graph_db_interface.GraphDB`: registration is middleware infrastructure, and the
OGM / KnowledgeGraphConnector remain the validated path for service *data*. It
creates instances only — never OWL classes or SHACL shapes, which pre-exist per
ADR 0003 (ontology-as-ground-truth). See ADR 0002 (Operation resolves via
Capability) and ADR 0004 (endpoint on both Service and Workflow).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple

from rdflib import Literal
from rdflib.namespace import RDF, XSD

from graph_db_interface import IRI
from kapps_semantic_middleware.vocabulary import CFC, SVC

if TYPE_CHECKING:
    from graph_db_interface import GraphDB


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


def build_workflow_endpoint(address: str, workflow_name: str) -> str:
    """Build the callable endpoint URL for a workflow.

    Matches aas_middleware's route ``POST /workflows/{name}/execute``.
    """
    return f"{address.rstrip('/')}/workflows/{workflow_name}/execute"


# --------------------------------------------------------------------------- #
# Ground-truth assertions and low-level helpers.
# --------------------------------------------------------------------------- #


def assert_class_registered(
    db: "GraphDB", class_iri: IRI, base_iri: IRI, named_graph: Optional[IRI] = None
) -> None:
    """Assert a class pre-exists as the required kind (ADR 0003).

    Valid iff ``class_iri == base_iri`` or ``db.is_subclass(class_iri, base_iri)``.
    A non-existent class makes ``is_subclass`` return False, so this also catches a
    missing class. Checks within ``named_graph`` when given, so a demo/test scenario
    isolated in its own graph is validated against that graph.

    Raises:
        OntologyGroundTruthError: If the class is missing or not the required subclass.
    """
    if class_iri != base_iri and not db.is_subclass(
        class_iri, base_iri, named_graph=named_graph
    ):
        raise OntologyGroundTruthError(
            f"Class {class_iri} must be {base_iri} or a subclass thereof, "
            "but it is not registered as such in the knowledge graph. "
            "Types are ontology-ground-truth (ADR 0003): author the class first."
        )


def _delete_all(
    db: "GraphDB", sub: IRI, pred: IRI, named_graph: Optional[IRI] = None
) -> None:
    """Delete every triple matching (sub, pred, *) by pattern.

    Uses a SPARQL ``DELETE WHERE`` so the object need not be matched by value or
    type. This matters because typed literals (e.g. an ``xsd:anyURI`` address) can
    round-trip back through the store as a different Python type than they were
    written as, which would make a delete-by-retrieved-triple silently no-op.
    """
    inner = f"<{sub}> <{pred}> ?o ."
    if named_graph is not None:
        sparql = f"DELETE WHERE {{ GRAPH <{named_graph}> {{ {inner} }} }}"
    else:
        sparql = f"DELETE WHERE {{ {inner} }}"
    db.query(sparql, update=True)


# --------------------------------------------------------------------------- #
# Registration (instances only).
# --------------------------------------------------------------------------- #


def register_service(
    db: "GraphDB",
    *,
    resource_iri: IRI,
    service_iri: IRI,
    service_class: IRI,
    address: str,
    named_graph: Optional[IRI] = None,
) -> None:
    """Register a Service instance for a resource and set its base address.

    Idempotent. Raises OntologyGroundTruthError if ``service_class`` is not
    ``svc:Service`` or a subclass.
    """
    assert_class_registered(db, service_class, SVC.Service)

    triples: List[Tuple] = [
        (service_iri, RDF.type, service_class),
        (resource_iri, SVC.hasService, service_iri),
        (service_iri, SVC.isServiceOf, resource_iri),
    ]
    db.triples_add(triples, check_exist=True, named_graph=named_graph)

    _delete_all(db, service_iri, SVC.address, named_graph)
    db.triple_add(
        (service_iri, SVC.address, Literal(str(address), datatype=XSD.anyURI)),
        named_graph=named_graph,
    )


def register_workflow(
    db: "GraphDB",
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

    Idempotent. Raises OntologyGroundTruthError if ``workflow_class`` is not a
    ``svc:Workflow`` subclass or ``capability_class`` is not a ``cfc:Capability``
    subclass.
    """
    assert_class_registered(db, workflow_class, SVC.Workflow)
    assert_class_registered(db, capability_class, CFC.Capability)

    triples: List[Tuple] = [
        (capability_iri, RDF.type, capability_class),
        (resource_iri, CFC.hasCapability, capability_iri),
        (workflow_iri, RDF.type, workflow_class),
        (service_iri, SVC.hasWorkflow, workflow_iri),
        (workflow_iri, SVC.isWorkflowOf, service_iri),
        (capability_iri, SVC.realizedByWorkflow, workflow_iri),
        (workflow_iri, SVC.realizesCapability, capability_iri),
    ]
    db.triples_add(triples, check_exist=True, named_graph=named_graph)

    _delete_all(db, workflow_iri, SVC.endpoint, named_graph)
    db.triple_add(
        (workflow_iri, SVC.endpoint, Literal(str(endpoint), datatype=XSD.anyURI)),
        named_graph=named_graph,
    )


# --------------------------------------------------------------------------- #
# Deregistration (remove reachability, preserve individuals).
# --------------------------------------------------------------------------- #


def deregister_service(
    db: "GraphDB", service_iri: IRI, named_graph: Optional[IRI] = None
) -> None:
    """Remove a Service's reachability (address + all workflow/state endpoints).

    Preserves every rdf:type and structural link triple, so the graph keeps a
    record of which services and workflows have existed (paper: availability vs.
    existence).
    """
    _delete_all(db, service_iri, SVC.address, named_graph)

    for _, _, wf_iri in db.triples_get(
        sub=service_iri, pred=SVC.hasWorkflow, named_graph=named_graph
    ):
        _delete_all(db, wf_iri, SVC.endpoint, named_graph)

    for _, _, sp_iri in db.triples_get(
        sub=service_iri, pred=SVC.hasStateProperty, named_graph=named_graph
    ):
        _delete_all(db, sp_iri, SVC.endpoint, named_graph)


# --------------------------------------------------------------------------- #
# Resolution + provenance.
# --------------------------------------------------------------------------- #


def resolve_operation_endpoint(db: "GraphDB", operation_iri: IRI) -> Tuple[IRI, str]:
    """Resolve an Operation to an invokable Workflow endpoint (ADR 0002).

    Chain: ``Operation --cfc:implementsCapability--> Capability
    --svc:realizedByWorkflow--> Workflow --svc:endpoint--> url``. An unreachable
    (deregistered/offline) workflow has no ``svc:endpoint``, so it will not match.

    Returns:
        (workflow_iri, endpoint_url) for the first matching workflow.

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
    result = db.query(sparql, convert_bindings=True)

    bindings = (
        result.get("results", {}).get("bindings", []) if isinstance(result, dict) else []
    )
    if not bindings:
        raise OperationResolutionError(
            f"Operation {operation_iri} cannot be resolved to any online Workflow "
            "(no capability realized by a workflow with a current endpoint)."
        )

    # With convert_bindings=True, each binding is flattened to {var: python_value};
    # a URI binding is already an IRI, a literal is its Python value.
    binding = bindings[0]
    workflow_iri = IRI(str(binding["wf"]))
    endpoint_url = str(binding["url"])
    return workflow_iri, endpoint_url


def record_operation_outcome(
    db: "GraphDB",
    *,
    operation_iri: IRI,
    workflow_iri: IRI,
    success: bool,
    result: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    named_graph: Optional[IRI] = None,
) -> None:
    """Record execution provenance on an Operation (R12 writeback).

    Idempotent: existing provenance for the operation is replaced. Records the
    acting workflow, success flag, timestamp, and optional serialized result.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    for pred in (
        SVC.executedByWorkflow,
        SVC.executionSuccess,
        SVC.executionTimestamp,
        SVC.executionResult,
    ):
        _delete_all(db, operation_iri, pred, named_graph)

    triples: List[Tuple] = [
        (operation_iri, SVC.executedByWorkflow, workflow_iri),
        (operation_iri, SVC.executionSuccess, Literal(bool(success), datatype=XSD.boolean)),
        (
            operation_iri,
            SVC.executionTimestamp,
            Literal(timestamp.isoformat(), datatype=XSD.dateTime),
        ),
    ]
    if result is not None:
        triples.append(
            (operation_iri, SVC.executionResult, Literal(str(result), datatype=XSD.string))
        )
    db.triples_add(triples, check_exist=True, named_graph=named_graph)
