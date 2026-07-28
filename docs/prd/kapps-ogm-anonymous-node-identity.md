# PRD: anonymous-node identity and the write path in kapps_ogm

**Origin**: wayfinder ticket `EHoffm/kapps_semantic_middleware#52` ("Resource instantiation: how
connection metadata gets into the instance"), grilled 2026-07-28. The session started from
`SAWeindel/kapps_ogm#4` and found that #4 describes one symptom of a larger structural gap.
**Status**: requirement capture. No `kapps_ogm` code written from this document yet.
**Audience**: `kapps_ogm` maintainer (Sören), ontology engineering (Ratan), and whoever picks up the
scenario-3 implementation set.
**Related**: `SAWeindel/kapps_ogm#1` (range resolution), `#2` (validated single-triple append),
`#3` (SHACL support — this document depends on it for one requirement), `#4` (commit relocates blank
nodes), `#46` (dirty `OGM` repository). Root ADR 0002 in this repo is amended by this work.

## Problem

`kapps_ogm` has no concept of identity for the anonymous node behind a `COMPLEX` property, and its
write path treats the TBox as exhaustive. Both assumptions are false for every parameter node in the
Circular Factory, and together they make the scenario-3 TransferUnit unusable after one write.

The domain ontology declares what a parameter **is** (`inf:hasValue`, `tu:hasUnit`); the ABox
additionally carries what a connector needs to **reach** it (`inf:hasMQTTTopic`,
`inf:hasMQTTSetTopic`, `inf:hasMQTTBrokerIP`). Three of five triples on every parameter node are
undeclared by the domain restriction, deliberately — the domain and connector TBoxes are not
connected (`#25`). Under the Open World Assumption that is not merely legal, it is the normal case.

### Stage 1 — provisioning silently produces a dead parameter

`ogm.commit(instance_iri=ConveyorBelt1_left, data={tu:hasConveyorSpeed: [{…, inf:hasMQTTTopic: […]}]})`:

| Step | Behaviour |
|---|---|
| `ogm.py:380` | scope derived from the payload, including the MQTT chain |
| `property_spec.py:320` | `_specify_complex_property(prop_iri, ogm)` **takes no `nested_scope`** — the nested spec is the range restriction and nothing else |
| `node_validator.py:66` | `WARNING Unknown properties in data for ClassSpec None: {inf:hasMQTTTopic, …}` — warn only |
| `class_spec.py:104-106` | `model_config = ConfigDict(extra="forbid")` assigned **after** `create_model`; verified inert on pydantic 2.13.4, so extras are silently ignored |
| `node_serializer.py:57` | serialises from `_iri_fields` — declared properties only |

The three MQTT triples never reach the graph. No exception, one warning. `ogm.create` fails
identically (same `materialize` → `to_triples` path). **There is no OGM write path today that can
carry a property the range restriction does not declare.**

### Stage 2 — the first ordinary write destroys the wiring

- `ogm.py:221` — `_fetch_complex_property` reads all five triples, then `list(property_data_dict.values())`
  **discards the bnode key**. Identity dies at *read*.
- `node_data_formatter.py:114` — no id ⇒ `_assign_id` ⇒ anonymous spec ⇒ `db.new_blank_id()`. Pydantic
  then ignores the `id` key entirely (anonymous models have no `id` field).
- `node_serializer.py:276` — mints another fresh `BNode`, on both sides of the diff.
- `core.py:285` — groups keyed by bnode label never compare equal ⇒ whole-group DELETE + INSERT.

The emitted transaction renders blank nodes as *variables*, so the DELETE matches the real node by
structure:

```sparql
DELETE { <…ConveyorBelt1_left> tu:hasConveyorSpeed ?oldbn1 .
         ?oldbn1 tu:hasUnit "m/s" . ?oldbn1 inf:accessMode "readwrite" . }
INSERT { <…ConveyorBelt1_left> tu:hasConveyorSpeed ?newbn1 .
         ?newbn1 inf:hasValue 1.4 . ?newbn1 tu:hasUnit "m/s" . ?newbn1 inf:accessMode "readwrite" . }
WHERE  { <…ConveyorBelt1_left> tu:hasConveyorSpeed ?oldbn1 .
         ?oldbn1 tu:hasUnit "m/s" . ?oldbn1 inf:accessMode "readwrite" .
         BIND(BNODE() AS ?newbn1) }
```

The link is deleted; the old node keeps topic, set topic and broker with **no inbound edge** —
unreachable — and the new node cannot reach the device. This is `#4`, with the additional finding
that `graph_db_interface.triples_update` builds **two separate** blank-node→variable maps
(`triple_multi.py:394-400`, `414-416`), so a Python-stable `BNode` on both sides still becomes a
freshly minted store node on the INSERT side. Identity preservation is therefore impossible today
without a change in `graph_db_interface` as well.

### Stage 3 — scenario 3 cannot survive its own second startup

Restart ⇒ registration finds no connection metadata ⇒ ADR 0015 row 3 ⇒ auto-provision ⇒ Stage 1,
which cannot write metadata. The resource is permanently unwireable and each cycle leaks another
orphan group. Not limited to the committed-value pattern: ADR 0015's write-back rule alone triggers
it on a pure locator.

## Why skolemisation, and not the alternatives

The parameter node is a **dependent entity**: meaningless apart from the property that carries it,
but holding state that outlives a single write, and needing to be pointed at from outside. RDF's
blank node expresses the first half and withholds the second — deliberately, since a blank node is an
existential variable, not a record.

Three consequences decided this design:

1. A blank node has **no extent**. "Everything hanging off this node" is not a set the graph defines;
   it is whatever your last query saw.
2. A blank node **cannot be addressed**. `_:b1` in a SPARQL query is a fresh existential, not a
   reference. Nothing outside its own group can point at it — no PROV qualification, no
   `sh:targetNode`, no join across a history snapshot.
3. It can only be **re-found by matching a pattern from a named subject**, which is exactly what makes
   the current DELETE destructive.

[RDF 1.1 Concepts §3.5](https://www.w3.org/TR/rdf11-concepts/#section-skolemization) provides the
sanctioned remedy, and both of its sentences are load-bearing here:

> "Systems MAY systematically replace some or all of the blank nodes in an RDF graph with IRIs.
> Systems wishing to do this SHOULD mint a new, globally unique IRI (a Skolem IRI) for each blank node
> so replaced. This transformation **does not appreciably change the meaning of an RDF graph**,
> provided that the Skolem IRIs do not occur anywhere else. It does however **permit the possibility
> of other graphs subsequently using the Skolem IRIs, which is not possible for blank nodes**."
>
> "Systems that want Skolem IRIs to be recognizable outside of the system boundaries SHOULD use a
> well-known IRI with the registered name `genid` … whose path component starts with
> `/.well-known/genid/`."

The first sentence is the semantic guarantee: the domain ontology's modelling is unchanged. The second
is precisely our requirement — PROV qualification, SHACL focus nodes and history joins are all "other
graphs subsequently using the node", which RDF says is impossible for a blank node.

Two conditions attach to the guarantee and become normative rules below: the IRIs must be globally
unique and never reused, and **nothing new may be asserted about the node** — no `rdf:type`, no class
membership, no annotation.

Supporting literature, and the reason this matters beyond correctness: the KAPPS paper is reviewed by
people who work on exactly this. [Hogan, Arenas, Mallea and Polleres (JWS 2014)](https://aidanhogan.com/docs/blank_nodes_jws.pdf)
found 25.7% of unique RDF terms in BTC-2012 are blank nodes used overwhelmingly as containers for
things that have no IRI yet, and propose canonical-labelling Skolemisation as the remedy.
[Hernández, Gutierrez and Hogan (ISWC 2018)](https://aidanhogan.com/docs/certain_answers_sparql_blank_nodes.pdf)
formalise the RDF-versus-SPARQL mismatch — RDF defines data blank nodes as existentials, SPARQL treats
them as constants — which is the mismatch a structural-match write path silently relies on. Daniel
Hernández is a co-author of the KAPPS paper.

**Rejected alternatives**

- *Keep blank nodes, preserve their labels in Python.* Fixes the orphaning but leaves the node
  unaddressable, so R5/R12 (PROV) and R7/R9 (SHACL focus nodes) stay structurally unsatisfiable, and
  two parameter nodes with identical declared content stay ambiguous.
- *Whole-group replacement, re-emitting declared and undeclared triples together.* Cheapest, stays
  inside `kapps_ogm`, but it is a closed-world write over a node with no extent: any triple added
  between fetch and commit is destroyed (a lost update the OGM creates, not the store), the atomic
  unit has no ontological basis, and identity churn breaks paper requirements R3, R5, R12 and R14.
- *Name the parameter node in the domain ontology.* Works today with no OGM change, but pushes naming
  onto twenty domain engineers and abandons a modelling pattern that is locked across the circular
  factory.
- *Declare connection metadata in the domain property's range.* No code change at all, but reverses
  `#25`, makes every domain engineer restate the protocol contract per parameter, and moves the IT/OT
  leak risk into middleware code.

## Requirements

**R1 — Identity at read.** `_fetch_complex_property` must keep the bnode/IRI key it currently discards
(`ogm.py:221`), so the nested `Node.id` is the node's actual identifier.

**R2 — Skolemisation on write.** When persisting an anonymous node the OGM mints a globally unique
Skolem IRI whose path starts `/.well-known/genid/`, in place of `BNode(db.new_blank_id())`
(`node_serializer.py:276`). It asserts **nothing else** about the node: no `rdf:type`, no annotation.
The current code already satisfies the type half — `to_triples` emits type triples only
`if self.class_spec and self.class_spec.iri`, and an anonymous ClassSpec has `iri=None`.

**R3 — Address resolution, never re-minting.** On write the target is resolved in this order:
(1) the address recorded in `Node.data`; (2) mint, only if this is a genuinely new node; (3) otherwise
**raise**. An unresolvable target must never silently become a new node.

**R4 — The address is invisible in the projection.** The materialised model of an anonymous node
carries its IRI out of band and serialises exactly as today — a dict of declared properties, no `id`
key. Implementation seam: `ClassSpec.pydantic_base_model` (already exists, `class_spec.py:38`) is set
to an `AnonymousNodeModel` carrying `_node_iri` as a pydantic `PrivateAttr`. Verified on pydantic
2.13.4: private attributes are absent from `model_dump()`, `model_dump_json()` and
`model_json_schema()`, so the address cannot leak northbound, into OpenAPI, or into `to_triples`.
Note that it does **not** survive a dump→revalidate round trip, which is why R3 makes `Node.data` the
authoritative carrier and the private attribute only a mirror.

**R5 — Per-triple diff.** With an IRI subject, `group_triples_by_bnode` places each triple in its own
group and the diff reduces to what actually changed, with no further work. A no-change commit becomes
a no-op, undeclared triples appear on neither side, and the write stays a single atomic DELETE/INSERT.

**R6 — Guard against top-level fetch.** `ogm.fetch` on a Skolem IRI must raise a clear
"anonymous node, fetch its parent" error rather than today's `ValueError: Could not determine class
IRI` (the node has no `rdf:type` by R2).

**R7 — Merged effective shape.** The effective nested `ClassSpec` of a parameter property is the union
of its own range restriction and the restrictions of every **interface** resolved for that node.
Justification is standard entailment, not convention: `belt tu:hasConveyorSpeed _:b` plus
`tu:hasConveyorSpeed rdfs:subPropertyOf inf:isInterfaceAccessibleMQTTParameter` entails
`belt inf:isInterfaceAccessibleMQTTParameter _:b` (rdfs7), and with a range on that superproperty,
`_:b rdf:type C_mqtt` (rdfs3) — alongside `_:b rdf:type C_speed` from the domain range. The node **is**
an instance of the intersection; the OGM computing it is implementing the entailment.

Mechanically this subsumes `#1`: `specify` must merge anonymous restriction ranges instead of raising
on arity, and `_specify_complex_property`'s query must collect ranges across `rdfs:subPropertyOf*`.
The existing loop already merges multiple `?range` bindings correctly (`property_spec.py:468-514`),
so the change is small. Conflict rules to define: same property twice with the same datatype is fine;
incompatible datatypes raise (an ontology error); differing cardinalities take the most restrictive;
a named class mixed with an anonymous restriction raises.

**R8 — The interface is resolved per instance, from three sources, as a union.** A protocol must not
be forced into a domain TBox: own-built hardware may not know its protocol at ontology-deployment
time, and two machines of one class may speak different protocols. Sources:

1. **ABox evidence** — the node already carries `inf:hasMQTTTopic` ⇒ merge the MQTT interface.
2. **Embedding code** — supplied by the middleware, which is how the *first* provisioning write knows
   what shape to write.
3. **TBox marker** — `rdfs:subPropertyOf inf:isInterfaceAccessible…`, optional, for hardware whose
   protocol is fixed by its supplier.

All resolved interfaces are merged; a dual-homed parameter legitimately carries several. Embedding
code may mark its declaration **authoritative**, which selects the shape and drives write-back removal
of stale metadata, so protocol migration is possible. Whether a connector is actually wired remains
the connector registry's decision, not the spec's. **Consequence:** the effective spec is
instance-dependent, so a spec cache must be keyed on `(class, scope, resolved interfaces)`.

**R9 — Views are selected by merge depth.** The interface hierarchy is ordered so that northbound-safe
content sits above protocol-specific content:

| View | Merges | Contains |
|---|---|---|
| user (northbound REST) | domain restriction + `inf:isInterfaceAccessibleParameter` | value, unit, access mode |
| wiring (connector registry) | the above + `inf:isInterfaceAccessible<Protocol>Parameter` | + topic, set topic, broker |

A broker address is therefore **physically absent** from the served model, with no filtering step —
the restriction is the projection. This constrains how Ratan authors the hierarchy: generic,
northbound-safe terms on the parent property; protocol connection details on the protocol subproperty.

**R10 — Nothing derived from OWL may produce a required field.** `someValuesFrom` currently sets
`min_count = 1` (`property_spec.py:495`), which `NodeValidator` correctly downgrades to a warning
under the OWA while `to_pydantic_field` turns it into `Field(default=...)` — a hard requirement. Under
the Open World Assumption the absence of a triple is incompleteness, never falsity. Requiredness is a
closed-world statement and must come from SHACL `sh:minCount` (`#3`). `allValuesFrom` is the correct
vocabulary for typing, since it constrains all values rather than asserting one exists.

**R11 — Blank-node identity in `graph_db_interface`.** `triples_update` must build **one** blank-node→
variable map shared across the DELETE and INSERT patterns, emitting `BIND(BNODE() AS ?v)` only for
blank nodes exclusive to the new side. A `BNode` appearing on both sides *is* the same node and must
render as the same variable. Independent of skolemisation, and correct either way.

**R12 — Migration, in both directions.** Skolemisation happens on first write to a node the OGM
touches, plus an explicit idempotent `ogm.skolemize(instance_iri, class_scope=…)` for converting a
whole resource up front. Its inverse `ogm.deskolemize(...)` replaces Skolem IRIs with blank nodes
again, and the pair must round-trip: `deskolemize(skolemize(g))` is isomorphic to `g`, and each call is
idempotent. The inverse is not a nicety — it is what makes the transformation demonstrably
meaning-preserving under §3.5, and it is needed to export a graph in the lean, blank-node form that
publication, federation and hand-authored seed files expect.

Authored Turtle is never rewritten: domain experts keep writing `[ … ]` and must never hand-author a
`genid` IRI. Store and file then differ in form, never in meaning — which is exactly what §3.5's first
sentence licenses. `#46` must be resolved **before** any migration, or three malformed parameters get
skolemised into permanence.

## Worked example — TransferUnit1, one belt, MQTT-controlled speed

**Interface ontology (`inf:`, INF-owned).** Today both marker properties have no `rdfs:range` at all
and the MQTT terms are loose vocabulary. They become real restrictions, split by northbound-safety:

```turtle
inf:isInterfaceAccessibleParameter a owl:ObjectProperty ;
    rdfs:range [ a owl:Class ; owl:intersectionOf (
        [ a owl:Restriction ; owl:onProperty inf:accessMode ; owl:allValuesFrom xsd:string ] ) ] .

inf:isInterfaceAccessibleMQTTParameter a owl:ObjectProperty ;
    rdfs:subPropertyOf inf:isInterfaceAccessibleParameter ;
    rdfs:range [ a owl:Class ; owl:intersectionOf (
        [ a owl:Restriction ; owl:onProperty inf:hasMQTTTopic    ; owl:allValuesFrom xsd:string ]
        [ a owl:Restriction ; owl:onProperty inf:hasMQTTBrokerIP ; owl:allValuesFrom xsd:string ]
        [ a owl:Restriction ; owl:onProperty inf:hasMQTTSetTopic ; owl:allValuesFrom xsd:string ] ) ] .
```

**Domain ontology (`tu:`).** Gets *shorter* — `inf:accessMode` moves to `inf:`, and the subproperty
line is now optional:

```turtle
tu:hasConveyorSpeed a owl:ObjectProperty ;
    rdfs:domain tu:ConveyorBelt ;
    rdfs:range [ a owl:Class ; owl:intersectionOf (
        [ a owl:Restriction ; owl:onProperty inf:hasValue ; owl:allValuesFrom xsd:float  ]
        [ a owl:Restriction ; owl:onProperty tu:hasUnit   ; owl:allValuesFrom xsd:string ] ) ] .
```

**Provisioning.** Embedding code declares the belt's speed MQTT (R8 source 2), so the effective nested
spec is the union of the three restrictions above. `NodeValidator` is silent — every property is
declared — the model keeps all five values, and `to_triples` emits five triples on a minted Skolem IRI:

```turtle
tui:ConveyorBelt1_left a owl:NamedIndividual, tu:ConveyorBelt ;
    tu:hasConveyorSpeed <https://w3id.org/circularfactory/.well-known/genid/ab12> .

<https://w3id.org/circularfactory/.well-known/genid/ab12>
    tu:hasUnit "m/s" ; inf:accessMode "readwrite" ;
    inf:hasMQTTTopic "TransferUnit1/ConveyorBelt/left/speed" ;
    inf:hasMQTTSetTopic "TransferUnit1/ConveyorBelt/left/speed_set" ;
    inf:hasMQTTBrokerIP "127.0.0.1" .
    # no rdf:type — meaning preserved per §3.5; still an anonymous node, now addressable
```

**Northbound projection** (unchanged from today, byte for byte):

```python
{"id": "…#ConveyorBelt1_left",
 "tu-hasConveyorSpeed": [ {"inf-hasValue": [], "tu-hasUnit": ["m/s"], "inf-accessMode": ["readwrite"]} ]}
```

**A value update:**

```sparql
DELETE { <…/.well-known/genid/ab12> inf:hasValue 12.1 }
INSERT { <…/.well-known/genid/ab12> inf:hasValue 1.4 }
WHERE  { <…/.well-known/genid/ab12> inf:hasValue 12.1 }
```

One atomic transaction. Unit, access mode and all three MQTT triples are on neither side. **Restart
then finds its metadata and takes ADR 0015 row 1.**

## Defects found along the way, each standing on its own

1. **`extra="forbid"` is inert** (`class_spec.py:104-106`) — assigned after `create_model`, so the
   core schema is already built. Verified on pydantic 2.13.4. The comment claims unknown properties
   are enforced at model level; they are silently ignored. A landmine: adding `model_rebuild()`
   without an undeclared-property policy would break every fetch of real data, since upstream instance
   data legitimately carries undeclared `rdfs:comment`.
2. **OWL-derived requiredness** (R10). Predicts a live failure: materialising `tui:ConveyorBelt1_left`
   as currently seeded should raise `ValidationError: inf-hasValue Field required`, because ADR 0024
   removed the value literals while the restriction still uses `someValuesFrom`.
3. **`NodeValidator`'s missing-required check is a strict-subset test** —
   `if data_properties < required_properties` (`node_validator.py:58`) passes silently whenever the
   data also carries any undeclared property, which is the normal case for a parameter node.
4. **`ogm.create` cannot derive its scope from the data** the way `commit` does
   (`ClassScope.from_node_data`, `ogm.py:380`), so every call needs an explicit `class_scope` or the
   ClassSpec comes back empty and `_recursive_update_nodes_class_spec` raises.
5. **`_specify_complex_property` ignores `nested_scope`** (`property_spec.py:320`) — a scope below a
   COMPLEX property is silently discarded. Known from `#29`; recorded here because R9 makes merge
   depth, not scope, the projection mechanism, so this stops being a blocker.

## Non-goals

- Entity deletion, still intentionally unsupported.
- Skolemising anything other than the anonymous node behind a `COMPLEX` property.
- Canonical (isomorphism-preserving) Skolemisation. Ours is identity-preserving per node, not
  content-derived; two structurally identical parameter nodes stay distinct, which is what a locator
  needs.
- SHACL shape authoring for parameter payloads — deferred with `#3`.

## Task split

**Ontology (Ratan).** Decide the minting authority for Skolem IRIs — `w3id.org/circularfactory`, an
sfb1574 host, or `urn:uuid:` — which binds the ontology CI/CD pipeline and, since these IRIs become
globally visible, the federation outlook in the paper's §7. Sign off that asserting nothing about the
Skolem IRI satisfies §3.5's meaning-preservation condition. Author the `inf:` hierarchy under R9's
northbound-safety ordering. Decide how SHACL shapes target parameter nodes (with `#3`).

**Domain experts.** Nothing. They keep authoring `[ … ]`, gain no obligation, and never hand-author a
`genid` IRI.

**`kapps_ogm` (Sören).** R1–R7, R10, R12. Four small loci for the identity work — keep the key in
`_fetch_complex_property`; `AnonymousNodeModel` via the existing `pydantic_base_model` seam; address
resolution in `_value_to_triples`; the top-level fetch guard — plus the merged-spec work in
`PropertySpec.specify`, and the five defects above.

**`graph_db_interface`.** R11.

**`kapps_semantic_middleware` (Etienne).** Supply R8 source 2 from embedding code; retire ADR 0023's
static-facet caching (its purpose was surviving whole-node replacement, which no longer happens);
correct `examples/transferunit.ttl` per R10 and R9.
