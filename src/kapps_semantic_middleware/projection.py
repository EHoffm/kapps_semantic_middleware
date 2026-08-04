"""The northbound projection: hide protocol metadata the ontology declares (ADR 0028).

A parameter node bundles two kinds of fact. What the value *means* is northbound content. This
includes its magnitude, its unit, whether a peer may write it. How the middleware *physically
reaches the device* is southbound only. This includes a broker address, a topic, an OPC-UA
endpoint. A peer that holds it could drive the machine directly. It would bypass every check the
middleware performs.

Separation by request for less is not possible. ``PropertySpec._resolve_effective_ranges`` merges
the whole ``rdfs:subPropertyOf*`` chain. There is no merge-depth parameter anywhere in the OGM
API. The shape a consumer gets always contains everything every level declares. The middleware
must therefore cut the bundle itself. It cuts on the **shape**, before any data receives read.

The ontology decides what gets cut, not the code. Walk upward from one parameter property
through three levels. The parameter property own range contributes value and unit. The
projection keeps both. Protocol markers between it and the root contribute broker and topic
data. The projection deletes all of it. The interface root own range contributes
``inf:accessMode``. The projection keeps it.

Derivation of the delete set from the **registry** instead received attempt. It is wrong. It
only knows the protocols this middleware happens to have code for. Measurement occurred on a
belt made reachable over both MQTT and OPC-UA with no OPC-UA binding registered. The registry-
derived set removed the MQTT metadata. It served ``inf:hasOPCUAEndpoint`` with its address. A
query to the ontology finds it. The ontology is authoritative about what a protocol parameter
*is* whether or not anyone wrote a connector.

Recomputation occurs **at every startup**. Consuming middlewares are decentralized. They live in
domain expert packages. The ontology may gain a protocol after one of them last looked.

A keep-list received consideration and rejection. It names what is safe. It drops the rest. It
reads as the safer construction. But it is a closed-world assertion in the serving path. The
architecture has exactly one closed-world moment by design (ADR 0025: SHACL at admission). It
would also hide new legitimate domain content by default. Twenty domain engineers would guard
something the OGM write path already governs.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Collection, Dict, Optional, Set

from graph_db_interface import IRI

from kapps_semantic_middleware.vocabulary import INF

logger = logging.getLogger(__name__)

RDFS_SUBPROPERTY_OF = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
RDFS_RANGE = "http://www.w3.org/2000/01/rdf-schema#range"
OWL_INTERSECTION_OF = "http://www.w3.org/2002/07/owl#intersectionOf"
OWL_ON_PROPERTY = "http://www.w3.org/2002/07/owl#onProperty"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"


class ProjectionError(RuntimeError):
    """The projection could not prove a payload safe. Nothing is served.

    Raise rather than log. A projection that cannot determine what to hide has exactly one safe
    behavior. Continue is not it. The failure would surface as a broker address on a public REST
    route.
    """


def southbound_properties(
    ogm: Any,
    parameter_property: Any,
    *,
    interface_root: Any = INF.isInterfaceAccessibleParameter,
) -> frozenset:
    """The properties a protocol marker contributes to one parameter shape.

    Empty for a property that is not interface-accessible at all. This is the ordinary answer for
    a plain object property like ``tu:hasConveyorBelt``.
    """
    markers = _protocol_markers(ogm, parameter_property, interface_root)
    if not markers:
        return frozenset()

    declared = _declared_by(ogm, markers)

    if not declared:
        # The ontology says this parameter is reached over some protocol. We cannot read what
        # that protocol contract is. Serve it. This would mean serve of fields we have not
        # classified. Refuse.
        raise ProjectionError(
            f"{parameter_property} is declared interface-accessible through "
            f"{', '.join(sorted(str(m) for m in markers))}, but no connection metadata could be "
            f"read from their rdfs:range. The northbound projection cannot prove what is safe "
            f"to serve, so nothing is served. Check that the interface ontology is loaded and "
            f"that its ranges are owl:Restriction or owl:intersectionOf class expressions."
        )

    return frozenset(declared)


def _protocol_markers(ogm: Any, parameter_property: Any, interface_root: Any) -> Set[str]:
    """The interface properties strictly between a parameter property and the interface root.

    Two exclusions, both load-bearing and neither obvious:

    - **The parameter property itself** matches ``subPropertyOf+ <root>``. Its own range is
      *domain* content. The value and its unit receive inclusion. Deletion of that would leave a
      payload with nothing in it.
    - **The interface root** matches too. GraphDB materialises *reflexive* ``rdfs:subPropertyOf``
      (RDFS rule rdfs6). ``+`` behaves like ``*``. Exclude it. The root own range receives
      treatment as protocol metadata. ``inf:accessMode`` receives deletion. This is the one
      interface fact a peer legitimately needs.

    Both were found by testing, not by read of the query.
    """
    rows = ogm.db.query(
        f"""
        SELECT DISTINCT ?marker WHERE {{
          <{parameter_property}> <{RDFS_SUBPROPERTY_OF}>+ ?marker .
          ?marker <{RDFS_SUBPROPERTY_OF}>+ <{interface_root}> .
          FILTER(?marker != <{parameter_property}> && ?marker != <{interface_root}>)
        }}
        """,
        convert_bindings=True,
    )["results"]["bindings"]
    return {str(row["marker"]) for row in rows}


def _declared_by(ogm: Any, markers: Set[str]) -> Set[str]:
    """Every property named by an ``owl:onProperty`` inside these properties ranges.

    Handle both range shapes the OGM itself accepts: an ``owl:intersectionOf`` list of
    restrictions, and a single bare ``owl:Restriction``. Read only the first. This would silently
    miss a protocol whose contract happens to have one term. A missed term is a leak.
    """
    values = " ".join(f"<{m}>" for m in markers)
    rows = ogm.db.query(
        f"""
        SELECT DISTINCT ?p WHERE {{
          VALUES ?marker {{ {values} }}
          ?marker <{RDFS_RANGE}> ?range .
          {{ ?range <{OWL_INTERSECTION_OF}>/<{RDF_REST}>*/<{RDF_FIRST}> ?restriction }}
          UNION
          {{ BIND(?range AS ?restriction) }}
          ?restriction <{OWL_ON_PROPERTY}> ?p .
        }}
        """,
        convert_bindings=True,
    )["results"]["bindings"]
    return {str(row["p"]) for row in rows}


def prune_southbound(
    class_spec: Any,
    *,
    ogm: Any,
    interface_root: Any = INF.isInterfaceAccessibleParameter,
    cache: Optional[Dict[str, frozenset]] = None,
) -> Any:
    """Return a copy of ``class_spec`` with each parameter protocol metadata removed.

    Recurse. A resource parameters hang off its components. Ask every nested spec the ontology
    what its own property contributes southbound. Two parameters reached over different protocols
    are each pruned correctly.

    The input is left untouched. The caller needs both shapes at once. The full one is for the
    bindings to read broker addresses out of. The pruned one is to serve.

    Copying is deliberately **shallow, per spec node**. Never use ``copy.deepcopy``. A spec
    property keys are ``IRI``. This subclasses ``rdflib.URIRef``. This subclasses ``str``. Deep-
    copy of one reconstructs it through ``str.__reduce_ex__``. It yields a plain ``URIRef``. It
    still compares equal. It has silently lost the ``lined`` accessor ``ClassSpec.to_pydantic_model``
    needs.

    ``cache`` maps property IRI to its southbound set. Pass one in to have it filled and reused.
    Every entry is a live SPARQL round trip. The caller usually needs the same answers again for
    the binding cross-check.
    """
    cache = {} if cache is None else cache
    removed: Set[str] = set()
    pruned = _pruned_copy(class_spec, ogm, interface_root, cache, removed)
    if removed:
        logger.debug(
            "Northbound projection removed %d protocol propert%s: %s",
            len(removed),
            "y" if len(removed) == 1 else "ies",
            ", ".join(sorted(removed)),
        )
    return pruned


def _pruned_copy(
    class_spec: Any,
    ogm: Any,
    interface_root: Any,
    cache: Dict[str, frozenset],
    removed: Set[str],
) -> Any:
    """One spec node, copied with each nested parameter protocol metadata gone."""
    properties = getattr(class_spec, "properties", None)
    if not properties:
        return class_spec

    kept = {}
    for prop_iri, prop_spec in properties.items():
        nested = getattr(prop_spec, "nested", None)
        if nested is not None:
            key = str(prop_iri)
            if key not in cache:
                cache[key] = southbound_properties(
                    ogm, prop_iri, interface_root=interface_root
                )
            nested = _pruned_copy(nested, ogm, interface_root, cache, removed)
            nested = _without(nested, cache[key], removed)
            prop_spec = copy.copy(prop_spec)
            prop_spec.nested = nested
        kept[prop_iri] = prop_spec

    pruned = copy.copy(class_spec)
    pruned.properties = kept
    return pruned


def _without(class_spec: Any, southbound: Collection[str], removed: Set[str]) -> Any:
    """A copy of one spec node with the named properties gone."""
    properties = getattr(class_spec, "properties", None)
    if not properties or not southbound:
        return class_spec

    kept = {}
    for prop_iri, prop_spec in properties.items():
        if str(prop_iri) in southbound:
            removed.add(str(prop_iri))
            continue
        kept[prop_iri] = prop_spec

    stripped = copy.copy(class_spec)
    stripped.properties = kept
    return stripped


def carries_southbound(value: Any, southbound: Collection[str]) -> Set[str]:
    """Which of the given protocol properties appear anywhere in a materialized payload.

    The projection assertion, usable as a guard or in a test. A northbound payload must contain
    none of them. A generated model field names are IRI-mangled. This matches the mangled form
    as well as the raw IRI. The former is what a served JSON body carries. The latter is what a
    spec or a graph dump does.

    Mangling goes through ``IRI.lined``. This is the OGM own field-name derivation. Do not use a
    local copy of the rule. A detector that mirrored it could drift. It would start report
    "clean" for a payload that leaks.
    """
    haystack = str(value)
    return {
        prop
        for prop in southbound
        if prop in haystack or IRI(prop).lined in haystack
    }


def cross_check(
    parameter_property: Any,
    ontology_declared: Collection[str],
    descriptor_declared: Optional[Collection[Any]],
) -> None:
    """Warn when a binding declared metadata and the ontology disagree.

    The ontology decides what is hidden. A descriptor ``connection_metadata`` says what that
    binding *reads*. They should coincide. Where they do not, one of the two drifted out of step.

    In the ontology only, the protocol contract grew a term this binding ignores. This case is
    safe northbound, since the projection hides the term either way. The connector may lack
    configuration.

    In the descriptor only, the code expects a term the ontology does not declare. That term
    will not survive a write, and it will not reach the connector. The parameter may come up
    silently dead. This is the direction that costs debugging time.

    Warned, never raised. A drift in either direction is a real deployment state. The projection
    is already safe because it follows the ontology.
    """
    if descriptor_declared is None:
        return

    ontology = {str(p) for p in ontology_declared}
    descriptor = {str(p) for p in descriptor_declared}
    if ontology == descriptor:
        return

    only_ontology = sorted(ontology - descriptor)
    only_descriptor = sorted(descriptor - ontology)
    logger.warning(
        "Connection metadata for %s disagrees between the ontology and its binding. "
        "Declared only in the ontology: %s. Declared only by the binding: %s. The projection "
        "follows the ontology, so nothing leaks; but a term the ontology does not declare will "
        "not survive a write, and the parameter may come up with no value flowing.",
        parameter_property,
        only_ontology or "none",
        only_descriptor or "none",
    )


def load_northbound(
    ogm: Any,
    *,
    instance_iri: Any,
    resource_class: Any,
    class_scope: Any = None,
    interface_root: Any = INF.isInterfaceAccessibleParameter,
) -> Any:
    """Fetch one resource with southbound metadata pruned before materialization.

    This is the "prune on load" half of ADR 0033: a consumer that fetches another middleware's
    datamodel into its own instance must run the same prune automatically, or it ends up holding
    the factory's broker addresses. The prune happens **before** any data is read through the spec,
    so the materialized result has no field a connection detail could ever occupy — this is not a
    data-side filter (ADR 0028).

    ``resource_class`` is a **required** keyword argument, not resolved from the graph the way a
    bare ``ogm.fetch(instance_iri=...)`` resolves it. The caller already knows the class from its
    own discovery/view query (ADR 0033's "Control Expert" flow queries ``tu:TransferUnit`` etc.
    before ever fetching a hit), so there is nothing left to resolve, and inventing a second
    class-resolution path here would duplicate ``OGM.fetch``'s own fallback for no benefit.

    The full (unpruned) ``ClassSpec`` this function builds is a purely local variable. It is never
    returned, never passed to the caller, and the fetch never runs against it — only the pruned
    spec is fetched with. Contrast this with ``wiring.py``'s ``plan_wiring``, which keeps *both*
    shapes because a serving instance's connector bindings need the full one to read a broker
    address or topic out of. A consumer that only *loads* a fetched datamodel has no binding to
    feed a full spec to, so nothing here needs to keep it around once pruning is done.

    Logging occurs at INFO level, one line per parameter property that had something removed. This
    is a bare library function with no REST stack or UI of its own to hang a ``/projection`` route
    or a panel on (those belong to separate tickets, #77 and #80, which build the REST connector
    and the controller UI on top of this primitive respectively) — an INFO log line is the one
    discoverability surface every caller gets for free regardless of what it's embedded in, and it
    costs no new route or schema.
    """
    cache: Dict[str, frozenset] = {}
    full_spec = ogm.get_class_spec(class_iri=resource_class, class_scope=class_scope)
    pruned_spec = prune_southbound(full_spec, ogm=ogm, interface_root=interface_root, cache=cache)
    _log_removed_per_parameter(instance_iri, cache)
    return ogm.fetch(
        instance_iri=instance_iri,
        class_spec=pruned_spec,
        class_scope=class_scope,
        materialize=True,
    )


def _log_removed_per_parameter(instance_iri: Any, cache: Dict[str, frozenset]) -> None:
    """Log one INFO line per parameter property that had southbound metadata removed."""
    for parameter_property, southbound in sorted(cache.items()):
        if not southbound:
            continue
        logger.info(
            "Loading %s pruned %d southbound propert%s from %s: %s",
            instance_iri,
            len(southbound),
            "y" if len(southbound) == 1 else "ies",
            parameter_property,
            ", ".join(sorted(southbound)),
        )
