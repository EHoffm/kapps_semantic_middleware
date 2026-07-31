# Local editable dependencies, with a bugfix-only policy on siblings

`kapps_ogm` and `graph_db_interface` are wired as local editable path dependencies
(`[tool.uv.sources]`), alongside the already-local `aas_middleware`, rather than consumed
from PyPI. Genuine correctness bugs found in any of the three sibling repos while building
`kapps_semantic_middleware` may be fixed directly in that sibling's checkout. New
functionality never goes into a sibling repo — it stays in `kapps_semantic_middleware`,
even where a sibling would be the more natural long-term home (see
`src/kapps_semantic_middleware/shacl_interop/docs/adr/0001-shacl-for-workflow-signatures.md`
for the concrete case: SHACL support belongs in `kapps_ogm`, but is built here first).

**Why**: `kapps_ogm`'s published PyPI release (0.1.2) has a `NameError` at
`property_spec.py:241` that breaks `fetch`/`create`/`commit` for any class with properties
in scope — i.e. almost every real call this project needs to make. Pointing at PyPI would
mean building on a known-broken dependency. Pointing at a local editable checkout lets the
bug be fixed where it lives instead of worked around. The bugfix-only line exists because
this project's implementation scope was explicitly bounded to `kapps_semantic_middleware`
itself — sibling repos are dependencies, not this project's surface, and only their defects
(not their feature set) are this project's problem to fix.

Every such fix must have a detailed changelog entry describing what changed and why.
