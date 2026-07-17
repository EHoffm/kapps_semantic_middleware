"""Shared IRI vocabulary for the KAPPS Semantic Middleware.

This module is the single source of truth for the ontology terms the middleware
reads and writes. Every other module (registration, execution, connectors,
tests, notebooks) imports its IRIs from here so that the Python code and the
published ontologies (Core `cfc:`, the project's `svc:` module, and the domain
`mes:` module) can never drift apart.

- `cfc:` — the published Circular Factory Core ontology
  (https://w3id.org/circularfactory/Core#). Term names below are verified against
  the 0.9.0 release.
- `svc:` — this project's Service ontology module
  (https://w3id.org/circularfactory/Service#), defined in
  `kapps_semantic_middleware/ontology/service.ttl`.
- `mes:` — Manufacturing Execution System domain ontology
  (https://w3id.org/circularfactory/MES#), defined in
  `kapps_semantic_middleware/ontology/mes.ttl`. Domain-facing; covers possession
  and handover-ability vocabulary per ADR 0012.
"""

from __future__ import annotations

from graph_db_interface import IRI

CORE_NS = "https://w3id.org/circularfactory/Core#"
SVC_NS = "https://w3id.org/circularfactory/Service#"
MES_NS = "https://w3id.org/circularfactory/MES#"

# Ontology document IRIs (no fragment) — used for owl:imports and named-graph loading.
CORE_ONTOLOGY = IRI("https://w3id.org/circularfactory/Core")
SVC_ONTOLOGY = IRI("https://w3id.org/circularfactory/Service")
MES_ONTOLOGY = IRI("https://w3id.org/circularfactory/MES")


class CFC:
    """Terms from the Core ontology (`cfc:`) that the middleware references."""

    # Classes
    Resource = IRI("Resource", base=CORE_NS)
    Capability = IRI("Capability", base=CORE_NS)
    EquippedCapability = IRI("EquippedCapability", base=CORE_NS)
    FlexibilityCapability = IRI("FlexibilityCapability", base=CORE_NS)
    ChangeabilityCapability = IRI("ChangeabilityCapability", base=CORE_NS)
    Operation = IRI("Operation", base=CORE_NS)
    Task = IRI("Task", base=CORE_NS)

    # Object properties
    implementsCapability = IRI("implementsCapability", base=CORE_NS)  # Operation -> Capability
    hasCapability = IRI("hasCapability", base=CORE_NS)  # Resource -> Capability


class SVC:
    """Terms from this project's Service ontology (`svc:`)."""

    # Classes
    Service = IRI("Service", base=SVC_NS)
    Workflow = IRI("Workflow", base=SVC_NS)
    StateProperty = IRI("StateProperty", base=SVC_NS)

    # Object properties
    hasService = IRI("hasService", base=SVC_NS)  # Resource -> Service
    isServiceOf = IRI("isServiceOf", base=SVC_NS)  # Service -> Resource
    hasWorkflow = IRI("hasWorkflow", base=SVC_NS)  # Service -> Workflow
    isWorkflowOf = IRI("isWorkflowOf", base=SVC_NS)  # Workflow -> Service
    hasStateProperty = IRI("hasStateProperty", base=SVC_NS)  # Service -> StateProperty
    isStatePropertyOf = IRI("isStatePropertyOf", base=SVC_NS)  # StateProperty -> Service
    realizedByWorkflow = IRI("realizedByWorkflow", base=SVC_NS)  # Capability -> Workflow
    realizesCapability = IRI("realizesCapability", base=SVC_NS)  # Workflow -> Capability
    providedByStateProperty = IRI("providedByStateProperty", base=SVC_NS)  # Capability -> StateProperty
    providesCapability = IRI("providesCapability", base=SVC_NS)  # StateProperty -> Capability
    precondition = IRI("precondition", base=SVC_NS)  # Workflow -> (SHACL-described args)
    outcome = IRI("outcome", base=SVC_NS)  # Workflow -> (SHACL-described return)

    # Datatype properties
    address = IRI("address", base=SVC_NS)  # Service -> xsd:anyURI (base URL)
    endpoint = IRI("endpoint", base=SVC_NS)  # Workflow|StateProperty -> xsd:anyURI (full URL)
    lastHeartbeat = IRI("lastHeartbeat", base=SVC_NS)  # Service -> xsd:dateTime

    # Execution provenance (R12, ADR 0009) — written onto a cfc:Operation by execute()
    # Success is now carried by the terminal operationStatus (done/failed), not a separate boolean.
    operationStatus = IRI("operationStatus", base=SVC_NS)  # Operation -> xsd:string (queued/running/done/failed, ADR 0009)
    executedByWorkflow = IRI("executedByWorkflow", base=SVC_NS)  # Operation -> Workflow
    executionTimestamp = IRI("executionTimestamp", base=SVC_NS)  # Operation -> xsd:dateTime
    executionResult = IRI("executionResult", base=SVC_NS)  # Operation -> xsd:string


class MES:
    """Terms from this project's MES ontology (`mes:`), defined in ontology/mes.ttl."""

    # Classes
    HandoverAbility = IRI("HandoverAbility", base=MES_NS)  # Enumerated class with six individuals

    # Object properties
    hasPossession = IRI("hasPossession", base=MES_NS)  # Resource -> material-flow product
    isPossessedBy = IRI("isPossessedBy", base=MES_NS)  # material-flow product -> Resource
    hasHandoverAbility = IRI("hasHandoverAbility", base=MES_NS)  # Resource -> HandoverAbility
    complements = IRI("complements", base=MES_NS)  # HandoverAbility -> HandoverAbility (symmetric)

    # Handover-ability individuals (three complementary pairs)
    Put = IRI("Put", base=MES_NS)  # Source-active giving; complements Receive
    Receive = IRI("Receive", base=MES_NS)  # Passive counterpart of Put; complements Put
    Pick = IRI("Pick", base=MES_NS)  # Destination-active taking; complements Release
    Release = IRI("Release", base=MES_NS)  # Passive counterpart of Pick; complements Pick
    Pass = IRI("Pass", base=MES_NS)  # Both-active giving; complements Retrieve
    Retrieve = IRI("Retrieve", base=MES_NS)  # Both-active taking; complements Pass


class OperationStatus:
    """String values for svc:operationStatus (ADR 0009 lifecycle). Not IRIs / individuals."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ALL = (QUEUED, RUNNING, DONE, FAILED)
