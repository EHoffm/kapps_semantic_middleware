# #29 — Datamodel at startup: what `OGM.fetch(materialize=True)` actually yields

Research output for wayfinder ticket [#29](https://github.com/EHoffm/kapps_semantic_middleware/issues/29)
under map #24. Reproduced **live** on 2026-07-27 against the `OGM` repository on
`graphdb.iam-mms.kit.edu`, instance `tui:TransferUnit1`, using the current
`kapps_ogm` checkout (`d2d5e47`).

Prefixes: `tu:` `https://www.sfb1574.kit.edu/ontologies/TransferUnit#` ·
`tui:` `…/TransferUnitInstances#` · `inf:` `…/CrcInterfaces#`

## Answer

**Yes — with an explicit ClassScope that names the parameter properties.** Materialization produces
the nested datamodel (belts and barriers as sub-models, each parameter as a dict). Without such a
scope it produces the `id` and nothing else.

| Case | `class_scope` | ClassSpec | Materialized |
|---|---|---|---|
| A | `None` — *what `_load_resource_datamodel` passes today* | `props=0` | `{id}` only |
| B | `[[hasConveyorBelt], [hasLightBarrier]]` | 2 props, nested `props=0` | belts/barriers as **id-only refs** |
| C | `[[hasConveyorBelt, hasConveyorSpeed], [hasLightBarrier, isOccupied]]` | fully nested | ✅ parameters materialize |
| D | `[[hasConveyorBelt, hasConveyorSpeed, inf:hasValue]]` | identical to C | third level **silently ignored** |

The rule: **scope depth must equal graph depth, and the parameter property is the last element.**
`ClassSpec.specify` under `SCOPE` hydration keeps *only* the properties named in the scope
(`class_spec.py`, `properties = expected_properties`). It returns early when the scope is empty. An
unnamed property is an absent property, at every level.

## The five findings

### 1. `_load_resource_datamodel` materializes an empty shell

`middleware.py:803` calls `self.ogm.fetch(instance_iri=self.resource_iri, materialize=True)` with no
scope and no loader. Result: `props=0`, instance `{id}`. Not caught to date because scenarios 1 and 2
construct their middleware but never serve it. `on_start_up` never fires (that is #44).

This is **not** a defect to fix by erroring. The middleware acts on a projection. The graph holds the
information. A projection of a bare individual is legitimate. It serves a one-field datamodel.
#42's `class_scope` parameter is what makes it useful. The failure surface belongs at *use*. It
already exists — verified:

- writing an absent attribute → `ValueError: "…TransferUnit" object has no field "…hasConveyorBelt"`
- committing an undeclared property → `ValueError: Properties {tu:notAProperty} specified in class
  scope, but not found as property of class …`

### 2. A ClassScope cannot reach inside a metadata blanknode

`OGM._fetch_complex_property` issues `?bnode ?property ?value` — unfiltered. The scope is never
consulted. `PropertySpec._specify_complex_property` takes no `nested_scope` argument. Case D's extra
level produces no error and no effect. **→ ADR 0028.**

### 3. The blanknode's shape is the TBox restriction; the rest is silently dropped

`tu:isOccupied`'s `rdfs:range` restriction declares exactly one member, `inf:hasValue` (bool). The
fetch returned `rdfs:comment` as well. Materialization discarded it. It logged only
`WARNING Unknown properties in data for ClassSpec None: {rdfs:comment}` (`NodeValidator`, non-strict).

**Consequence for #40**: an MQTT topic asserted on the instance is dropped before any connector sees
it. This happens unless the restriction declares it. Current upstream restrictions declare **no**
MQTT metadata:

| property | restriction members |
|---|---|
| `tu:hasConveyorSpeed` | `inf:hasValue` (float), `tu:hasUnit` (str) |
| `tu:hasConveyorPosition` | `inf:hasValue` (float), `tu:hasUnit` (str) |
| `tu:isOccupied` | `inf:hasValue` (bool) |

Blanket `strict=True` is **not** an available remedy. Upstream instance data carries undeclared
`rdfs:comment`. Strict mode fails on ground truth. Hence the targeted check in ADR 0020.

### 4. The interface binding is on the property; the blanknode has no named class

The blanknode's only `rdf:type` values are the anonymous `owl:Restriction` nodes of the range. They
appear solely under inference. `_fetch_complex_property` queries
`FROM <http://www.ontotext.com/explicit>` — so they are never fetched. The binding upstream is a
property hierarchy. It is already asserted:

```
tu:hasConveyorSpeed  rdfs:subPropertyOf  inf:isInterfaceAccessibleMQTTParameter
                     rdfs:subPropertyOf  inf:isInterfaceAccessibleParameter
                     rdfs:subPropertyOf  inf:isAttribute
```

`inf:hasMQTTTopic`, `inf:hasMQTTBrokerIP` and `inf:InterfaceAccessibleMQTTParameter` all exist in the
repository's `inf:` vocabulary. Those superproperties currently carry **no** `rdfs:range`. This is
the only reason fetch works — see finding 5. **→ ADR 0020.**

### 5. One `rdfs:range` per property, or `kapps_ogm` raises

`PropertySpec.specify` raises `ValueError: Property … has multiple rdfs:range defined`. This blocks
both additive extension of the fixed upstream `tu:` properties. It blocks putting ranges on the
`inf:` interface superproperties (which would collide by inheritance). RDFS ranges are conjunctive.
The raise is a defect. **→ root ADR 0002**, plus a grilling session in `kapps_ogm` before the fix.

## Concrete field paths

Field names are `IRI.lined` and are kept in that form in production (ADR 0021). Abbreviating the
namespace as `«TU»` = `https_c__s__s_www_d_sfb1574_d_kit_d_edu_s_ontologies_s_TransferUnit_h` and
`«INF»` = `…_s_CrcInterfaces_h`:

```
«TU»_TransferUnit                                     model class / route root
├── id                                        → tui:TransferUnit1
├── «TU»_hasConveyorBelt      : list[«TU»_ConveyorBelt]
│   ├── id                                    → tui:ConveyorBelt1_left | _right
│   ├── «TU»_hasConveyorSpeed    : list[AnonymousClass]   ← COMPLEX, atomic
│   │   ├── «INF»_hasValue    : list[float]
│   │   └── «TU»_hasUnit      : list[str]
│   └── «TU»_hasConveyorPosition : list[AnonymousClass]   ← COMPLEX, atomic
│       ├── «INF»_hasValue    : list[float]
│       └── «TU»_hasUnit      : list[str]
└── «TU»_hasLightBarrier      : list[«TU»_LightBarrier]
    ├── id                                    → tui:LightBarrier1_front | _back
    └── «TU»_isOccupied          : list[AnonymousClass]   ← COMPLEX, atomic
        └── «INF»_hasValue    : list[bool]
```

Notes for #40/#41: every value is a **list** (RDF multiplicity), including scalars. The blanknode
models are literally named `AnonymousClass` and have **no `id`** — they are the terminal, atomic unit
(ADR 0017). Access mode and MQTT metadata are *absent* from this tree today. They enter only once the
restrictions declare them.

## Routes actually generated by the framework

Loading the Case-C instance and calling `generate_rest_api_for_data_model` produces:

```
GET   /«TU»_TransferUnit/
POST  /«TU»_TransferUnit/
GET   /«TU»_TransferUnit/{item_id}
PUT   /«TU»_TransferUnit/{item_id}
DELETE /«TU»_TransferUnit/{item_id}
```

**No attribute routes at all.** `get_contained_models_attribute_info` admits an attribute only if it
passes `is_identifiable_type`. `ClassSpec.to_pydantic_model` builds on plain `pydantic.BaseModel`.
Belts and barriers are invisible to the generator. They are not merely the speeds. ADR 0017's premise
("the deepest addressable thing is the whole belt list") is corrected there. The depth is **zero**.
#41 inherits nothing.

## Hygiene issues found

- **Stale evidence.** `kapps_ogm/scripts/output/` was last written at `ef74709`. This **pre-dates**
  `eb09f3d` (the `SCOPE` early-return). Those committed files show a shape the current code does not
  produce. #29's amendment cited them as ground truth. It should not have.
- **Dirty `OGM` repository.** Only `tui:LightBarrier1_back` has the correct blanknode shape.
  `ConveyorBelt1_left`, `ConveyorBelt1_right` and `LightBarrier1_front` have their parameter values
  **flattened to literals** (`tu:hasConveyorSpeed → 10.2`). Case C returned `[]` for them because of
  this. `?bnode ?property ?value` cannot match a literal. Leftover `inf:isAttribute` /
  `inf:isInterfaceAccessibleParameter` assertions from earlier experiments are also present.
  Reloading clean instance data is a prerequisite for any test written against this repository.

## Decisions this produced

| # | Decision | Record |
|---|---|---|
| 1 | Northbound projection is middleware-side; a scope cannot select within a parameter | ADR 0028 (amends 0018) |
| 2 | Conjunctive `rdfs:range`; the raise is a `kapps_ogm` defect | root ADR 0002 |
| 3 | Connectors match on the interface property; registry built from connector classes | ADR 0020 (amends 0016) |
| 4 | Unrecognised complex content is plain data, shown and readable, nothing wired | ADR 0020 |
| 5 | A resolved connector missing declared metadata fails loudly | ADR 0020 |
| 6 | Mangled IRIs in production, pretty-printing display-only; no domain IRIs in core | ADR 0021 |
| 7 | An empty projection is legitimate; failure belongs at use, and already raises | ADR 0018 (consequence) |
