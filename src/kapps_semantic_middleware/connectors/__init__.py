"""Connectors: the knowledge-graph connector and the semantic-connector seam.

Importing this package **registers the built-in binding descriptors** on
``semantic.default_registry``. That import is load-bearing rather than a convenience: a
middleware constructed without an explicit ``connector_registry`` gets the default one, and an
empty default registry would mean an empty prune set, which would mean the northbound
projection removes nothing and every served parameter carries its broker address and topics
(ADR 0028). The registry is what tells the projection which properties are southbound, so it
must be populated before anything is served — not merely before anything is wired.
"""

from kapps_semantic_middleware.connectors.knowledge_graph_connector import (
    KnowledgeGraphConnector,
)

# Imported for its registration side effect; `MQTTBinding` is re-exported so a caller can
# reference it directly (to build a restricted registry, or to override it).
from kapps_semantic_middleware.connectors.mqtt_binding import MQTTBinding
from kapps_semantic_middleware.connectors.semantic import (
    BindingDescriptor,
    ParameterBinding,
    Registration,
    SemanticConnectorRegistry,
    default_registry,
    semantic_connector,
)

__all__ = [
    "KnowledgeGraphConnector",
    "MQTTBinding",
    "BindingDescriptor",
    "ParameterBinding",
    "Registration",
    "SemanticConnectorRegistry",
    "default_registry",
    "semantic_connector",
]
