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
- `inf:` — the interface vocabulary: what makes a domain parameter reachable over a
  protocol. Authored for now under the existing CrcInterfaces IRI so scenario 3 stays
  vocabulary-compatible with the minimal example shared across `graph_db_interface` and
  `kapps_ogm`. CrcInterfaces is deprecated and the consolidation capstone (#39) re-homes
  these terms under the `inf:` name it mints — which is why they must only ever be reached
  through `class INF`, never inlined at a use site (ADR 0021). A rename is then one
  constant here plus a find-and-replace.
"""

from __future__ import annotations

from graph_db_interface import IRI

CORE_NS = "https://w3id.org/circularfactory/Core#"
SVC_NS = "https://w3id.org/circularfactory/Service#"
MES_NS = "https://w3id.org/circularfactory/MES#"
INF_NS = "https://www.sfb1574.kit.edu/ontologies/CrcInterfaces#"

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
    # Possession (Core's reified, time-bound model — verified against Core 0.9.0).
    PossessionState = IRI("PossessionState", base=CORE_NS)  # a Resource-holds-Workpiece state
    Workpiece = IRI("Workpiece", base=CORE_NS)

    # Object properties
    implementsCapability = IRI("implementsCapability", base=CORE_NS)  # Operation -> Capability
    hasCapability = IRI("hasCapability", base=CORE_NS)  # Resource -> Capability
    hasPossessor = IRI("hasPossessor", base=CORE_NS)  # Resource -> PossessionState
    hasPossessedWorkpiece = IRI("hasPossessedWorkpiece", base=CORE_NS)  # Workpiece -> PossessionState


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

    # Execution provenance (R12, ADR 0009) — written onto a cfc:Operation by the pull-and-run
    # terminal transition. Success is carried by the terminal operationStatus (done/failed).
    operationStatus = IRI("operationStatus", base=SVC_NS)  # Operation -> xsd:string (queued/running/done/failed, ADR 0009)
    executedByWorkflow = IRI("executedByWorkflow", base=SVC_NS)  # Operation -> Workflow
    executionTimestamp = IRI("executionTimestamp", base=SVC_NS)  # Operation -> xsd:dateTime
    executionResult = IRI("executionResult", base=SVC_NS)  # Operation -> xsd:string
    failureState = IRI("failureState", base=SVC_NS)  # Operation -> xsd:string (JSON resource-datamodel dump on failure)


class MES:
    """Terms from this project's MES ontology (`mes:`), defined in ontology/mes.ttl.

    Scope is now handover *ability* only: possession itself is Core material-flow state
    (``cfc:PossessionState`` / ``cfc:hasPossessor`` / ``cfc:hasPossessedWorkpiece``, see
    ``class CFC``), so this module no longer mints its own possession vocabulary (ADR 0012).
    """

    # Classes
    HandoverAbility = IRI("HandoverAbility", base=MES_NS)  # Enumerated class with six individuals

    # Object properties
    hasHandoverAbility = IRI("hasHandoverAbility", base=MES_NS)  # Resource -> HandoverAbility
    complements = IRI("complements", base=MES_NS)  # HandoverAbility -> HandoverAbility (symmetric)

    # Handover-ability individuals (three complementary pairs)
    Put = IRI("Put", base=MES_NS)  # Source-active giving; complements Receive
    Receive = IRI("Receive", base=MES_NS)  # Passive counterpart of Put; complements Put
    Pick = IRI("Pick", base=MES_NS)  # Destination-active taking; complements Release
    Release = IRI("Release", base=MES_NS)  # Passive counterpart of Pick; complements Pick
    Pass = IRI("Pass", base=MES_NS)  # Both-active giving; complements Retrieve
    Retrieve = IRI("Retrieve", base=MES_NS)  # Both-active taking; complements Pass


class INF:
    """Terms from the interface vocabulary (`inf:`).

    A **parameter** is one node hanging off a domain property, carrying the value together
    with everything needed to reach it over a protocol (ADR 0015). The terms split into two
    layers, and the split is load-bearing:

    - **Northbound-safe** — declared by the generic marker
      ``isInterfaceAccessibleParameter``: ``accessMode``, and the parameter's own domain
      content. Safe to serve to a peer.
    - **Southbound only** — declared by a protocol marker such as
      ``isInterfaceAccessibleMQTTParameter``: the connection metadata. A peer that learned
      the broker address and topics could drive the device directly and bypass the
      middleware, so this must never reach a northbound payload (ADR 0028).

    The core never decides which terms are southbound by name. A binding descriptor declares
    its own ``connection_metadata`` and the registry takes the union (ADR 0021, ADR 0028).
    """

    # Interface marker properties. A domain property becomes interface-accessible by being
    # rdfs:subPropertyOf one of these; the protocol marker is a subproperty of the generic
    # one, which is what makes the two range restrictions merge into one effective shape.
    isInterfaceAccessibleParameter = IRI("isInterfaceAccessibleParameter", base=INF_NS)
    isInterfaceAccessibleMQTTParameter = IRI(
        "isInterfaceAccessibleMQTTParameter", base=INF_NS
    )

    # Parameter content (northbound-safe).
    hasValue = IRI("hasValue", base=INF_NS)  # the live value; absent under the locator pattern
    accessMode = IRI("accessMode", base=INF_NS)  # "read" | "readwrite" (ADR 0015 facet)

    # MQTT connection metadata (southbound only).
    hasMQTTTopic = IRI("hasMQTTTopic", base=INF_NS)  # topic the device publishes readings on
    hasMQTTSetTopic = IRI("hasMQTTSetTopic", base=INF_NS)  # setpoint topic; readwrite only
    hasMQTTBrokerIP = IRI("hasMQTTBrokerIP", base=INF_NS)  # broker carrying both topics
    hasMQTTValuePath = IRI("hasMQTTValuePath", base=INF_NS)  # JSON envelope path; absent = raw scalar


class AccessMode:
    """String values for `inf:accessMode` (ADR 0015). Not IRIs / individuals.

    Absent or unrecognised means read-only: a parameter is never writable by accident of
    omission (ADR 0023).
    """

    READ = "read"
    READWRITE = "readwrite"
    ALL = (READ, READWRITE)


class OperationStatus:
    """String values for svc:operationStatus (ADR 0009 lifecycle). Not IRIs / individuals."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ALL = (QUEUED, RUNNING, DONE, FAILED)
