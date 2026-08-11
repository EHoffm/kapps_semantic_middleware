# #117 — What kadi-apy's documentation does, page by page

This memo summarizes AFK reading of the `kadi-apy` *stable* documentation (read 2026-08-11). It exists to give ticket #116 (docs pipeline choice) and the information-architecture decision something concrete to be shaped against. All findings below are derived from the supervisor's reading notes; no live re-verification was performed by the author.

## 1. Page inventory and order

A reader encounters the following structure via the sidebar navigation. Narrative guidance (Setup) precedes reference material (Usage).

| Order | Section | Pages | Content Type |
| :--- | :--- | :--- | :--- |
| 1 | **Setup** | Installation, Development, Upgrading, Configuration | Hand-written prose + config samples |
| 2 | **Usage** | Library, CLI, CLI Library | Mixed prose + auto-generated API ref |
| 3 | **Release history** | Changelog (0.1.0 … 0.51.0) | Auto-generated list |

**Landing page:** Introduces the library as a tool for Kadi4Mat REST API interaction. Notes two interfaces (OO Python, CLI) and OS support (Linux/Windows/macOS). Theme is `sphinx_rtd_theme`. No version switcher is visible in the navigation.

## 2. Hand-written prose vs generated API reference

The split favors reference material heavily in the Usage section.

- **Setup pages:** 100% hand-written prose (installation steps, config file explanation).
- **Library page:** Roughly ~80% auto-generated API reference (autodoc) and ~20% hand-written prose (intro, notes, basic usage patterns).
- **CLI page:** 100% auto-generated command reference (sphinx-click).

The documentation prioritizes completeness of the API surface over narrative tutorials in the Usage section.

## 3. How it teaches installation

**Command:**
```bash
pip3 install kadi-apy
```

**Assumptions:**
- Python >= 3.9 and `pip` are already present.
- User understands virtual environments (briefly acknowledged).
- Unix PATH is default; Windows requires separate environment variable configuration via control panel.

**Configuration & Authentication:**
- **Requirements:** Host URL (Kadi4Mat instance FQDN) and Personal Access Token (PAT).
- **PAT Creation:** Links out to separate Kadi4Mat docs; does not walk through creation internally.
- **Config File:** Lives in a "suitable location in your home directory" (exact OS paths not specified).
- **Methods:** Pass credentials to `KadiManager` directly, or use a config file (recommended).
- **CLI Helpers:** `kadi-apy config create`, `set-host`, `set-pat`.

## 4. How examples are presented

- **Library Page:** Inline code snippets within prose (e.g., `manager.record(id=1)`, `record.upload_file()`).
- **CLI Page:** Syntax templates only (e.g., `kadi-apy collections create [OPTIONS]`). No practical usage examples with real data.
- **Notebooks/Screenshots:** None found.
- **Testing Status:** No evidence that examples are executed during build. The `myst_parser` extension is present for Markdown authoring, but no `doctest` or `nbsphinx` execution extensions are listed.

## 5. What machinery produces it

**Builder:** Sphinx, hosted on Read the Docs.
**Theme:** `sphinx_rtd_theme`.
**Build Config:** `.readthedocs.yml` specifies Ubuntu 24.04, Python 3.13, install via `pip path: .[dev]`, `fail_on_warning: true`. Only HTML built.

| Extension | Purpose |
| :--- | :--- |
| `sphinx.ext.autodoc` | Auto-generate API docs from docstrings |
| `sphinx.ext.intersphinx` | Link to external docs (Python 3, Click) |
| `sphinx.ext.viewcode` | Link to source code from docs |
| `myst_parser` | Markdown authoring support |
| `sphinx_click` | Auto-generate CLI docs from Click commands |

**Versioning:** Version/release retrieved dynamically from package metadata. No visible version switcher in nav.

## 6. What this project cannot copy

`kadi-apy` is a client library for a single HTTP API; `kapps_semantic_middleware` is a semantic middleware with a knowledge graph, multi-process runtime, and a browser-driven UI. We can borrow the tooling (Sphinx/RTD), but the information architecture (IA) must be invented.

**Where kadi-apy's IA breaks for us:**
1.  **Runtime Complexity:** `kadi-apy` is "install & call". Our examples require `docker compose up` (GraphDB, MQTT broker). An "Installation" page cannot precede a "Concepts" page explaining why Docker is needed.
2.  **Learning Path:** `kadi-apy` splits Library vs CLI. Our value proposition is the scenario (Hello World → Door/Robot → Factory). The IA must be scenario-first, not interface-first.
3.  **Visuals:** `kadi-apy` has no UI. Our TransferUnit factory demo includes a live topology web page. Screenshots are mandatory for us to explain the system state; they are optional/absent for `kadi-apy`.
4.  **Prerequisites:** `kadi-apy` assumes Python/pip. We assume familiarity with GraphDB ontologies and MQTT topics. Reference material must include ontology diagrams, not just method signatures.

**Conclusion:** We cannot adopt their "Setup → Usage → Reference" flow. We require "Concepts → Quickstart (Docker) → Scenarios → API Reference". The API reference is secondary to understanding the graph topology that drives the API calls.
