"""The northbound projection: pruning southbound properties out of a ClassSpec (ADR 0028).

ADR 0026 concluded that a view *is* a merge depth, so the northbound datamodel physically
could not carry a broker address and no filtering step was needed. That premise does not hold
against the implementation: ``PropertySpec._resolve_effective_ranges`` walks the entire
``rdfs:subPropertyOf*`` chain and merges every anonymous range it finds, with no merge-depth
parameter anywhere in the OGM's API. Every ClassSpec is the full merge, and the full merge is
the southbound shape.

So the middleware realizes the shallow view itself, by removing the southbound properties from
the spec **before** fetching and handing the pruned spec to ``OGM.fetch(class_spec=…)``. The
ordering matters: the projection happens before any connection metadata is read out of the
store, rather than filtering it out of a materialized model afterwards. A data-side filter is a
step that can be forgotten or bypassed by a second code path; a spec-side prune means the
northbound model has no field to carry a broker address in.

Which properties are southbound is never decided here by name. The registry takes the union of
every registered binding's ``connection_metadata``, so the core names no protocol term
(ADR 0021) and a domain expert's own connector is projected for free.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Collection, Set

from graph_db_interface import IRI

logger = logging.getLogger(__name__)


def prune_southbound(class_spec: Any, southbound: Collection[str]) -> Any:
    """Return a copy of ``class_spec`` with every southbound property removed.

    Recurses into nested specs, because the connection metadata sits on the parameter node —
    one level below the resource — and a resource-rooted spec reaches it through the COMPLEX
    property.

    The input spec is left untouched: the caller needs both shapes at once. The full spec is
    what the bindings read to build their connectors, and the pruned one is what gets served
    (ADR 0028).
    """
    pruned = copy.deepcopy(class_spec)
    removed = _prune_in_place(pruned, {str(prop) for prop in southbound})
    if removed:
        logger.debug(
            "Northbound projection removed %d southbound propert%s: %s",
            len(removed),
            "y" if len(removed) == 1 else "ies",
            ", ".join(sorted(removed)),
        )
    return pruned


def _prune_in_place(class_spec: Any, southbound: Set[str]) -> Set[str]:
    """Strip southbound properties from a spec and its nested specs; report what went."""
    properties = getattr(class_spec, "properties", None)
    if not properties:
        return set()

    removed = set()
    for prop_iri in list(properties):
        if str(prop_iri) in southbound:
            del properties[prop_iri]
            removed.add(str(prop_iri))
            continue
        nested = getattr(properties[prop_iri], "nested", None)
        if nested is not None:
            removed |= _prune_in_place(nested, southbound)
    return removed


def carries_southbound(value: Any, southbound: Collection[str]) -> Set[str]:
    """Which southbound properties appear anywhere in a materialized payload.

    The projection's assertion, usable as a guard or in a test: a northbound payload must
    contain none of these. A generated model's field names are IRI-mangled, so this matches
    the mangled form as well as the raw IRI — the former is what a served JSON body actually
    carries, the latter what a spec or a graph dump does.

    Mangling goes through ``IRI.lined``, the OGM's own field-name derivation, rather than a
    local copy of the rule: a detector that mirrored it could drift and start reporting
    "clean" for a payload that leaks.
    """
    haystack = str(value)
    return {
        prop
        for prop in southbound
        if prop in haystack or IRI(prop).lined in haystack
    }
