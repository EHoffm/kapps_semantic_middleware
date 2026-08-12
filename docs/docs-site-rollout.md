# Standing up a documentation site for a KAPPS repository

Ticket [#137](https://github.com/EHoffm/kapps_semantic_middleware/issues/137). This is the
per-repository procedure that [#119](https://github.com/EHoffm/kapps_semantic_middleware/issues/119)
(`kapps_ogm`) and [#133](https://github.com/EHoffm/kapps_semantic_middleware/issues/133)
(`kapps_triplestore_interface`) invoke when they stand their release repository up.

**Invoke it, do not copy it.** The scripts are vendored per repository under
[#110](https://github.com/EHoffm/kapps_semantic_middleware/issues/110) because the three release at
their own pace. This document is the opposite case: one source for the *how*, so three repositories
cannot drift on the procedure. Improve it here.

Nothing in this document is a fresh decision.
[#116](https://github.com/EHoffm/kapps_semantic_middleware/issues/116) settled the pipeline and
proved it end to end on
[circularfactory/docs-pipeline-test](https://circularfactory.github.io/docs-pipeline-test/) across
two releases. Everything below is the transcription of that proof, plus the three things the run
taught that the decision could not.

## Before you start

You need the release repository to exist under `circularfactory`, and admin rights on it — steps 4,
5 and 6 change repository settings, not files.

You do **not** need anything private. #116 proved the build against three public GitHub pins, so the
docs pipeline does not inherit stream A's gate.

## 1. Vendor the Sphinx source

Copy `docs/site/` from this repository into the target repository, keeping the path. It contains
`conf.py`, the page skeleton, `requirements.txt`, `_static/`, and the workflow template.

Change only:

- **`project` and `release`** in `conf.py`. `release` reads the installed distribution version via
  `importlib.metadata`, so it needs the target's distribution name, not its import name.
- **The reference pages.** One page per module, not per area — #116's first attempt put 67
  signatures on a single 179k page and 2 on another. Split so the left sidebar becomes a real module
  index.
- **`icon_links`** in `html_theme_options`: the PyPI and repository URLs.

Leave the theme, the branding and `_static/custom.css` alone. They follow the SFB1574 site and are
not per-repository choices.

## 2. Decide what the landing page is

Two cases, and the choice is already made for all three repositories.

**`kapps_semantic_middleware` writes its own.** `docs/site/index.md` is authored, because
[#135](https://github.com/EHoffm/kapps_semantic_middleware/issues/135) planned a four-section site
and [#139](https://github.com/EHoffm/kapps_semantic_middleware/issues/139) wrote the front of it.
Leave it alone.

**`kapps_ogm` and `kapps_triplestore_interface` render their `README.md`.** Settled on
[#136](https://github.com/EHoffm/kapps_semantic_middleware/issues/136): neither has a page inventory
and neither needs one at 0.1.0, but a site whose landing page is placeholder text is worse than no
site. Rendering the README gives real content for no new prose, and it follows #135's principle one
level out — *"the two notebook pages **are** the notebooks"*. A page and a file that say the same
thing drift; one file cannot.

**Where the README is the landing page, editing it is editing a published page** — and in a
repository that publishes to PyPI it is a third thing again, because PyPI renders the README as the
project page. One file then serves the repository visitor, the PyPI project page and the
documentation landing page. Check all three before deciding it is finished.

This is why `kapps_ogm`'s README is
[#119](https://github.com/EHoffm/kapps_semantic_middleware/issues/119)'s work: at 429 bytes it is a
title, a licence line and an acknowledgement, which is not a project page and not a landing page.

## 3. Install the workflow — in the release repository only

Copy `docs/site/publish-workflow.yml` to `.github/workflows/docs.yml` **in the public release
repository**. It is deliberately not at `.github/workflows/` in a dev repository: it fires on `v*`
tags, and a dev repository's tags are not releases.

Nothing generated is ever committed. The workflow builds and deploys through
`upload-pages-artifact` + `deploy-pages`, so `main` keeps its one clean release commit of source
only, and #110's human review gate never has to read built HTML.

## 4. Set Pages to build from the workflow

```bash
gh api --method POST repos/circularfactory/<repo>/pages -f build_type=workflow
```

**Only for the three tool repositories.** `ci_test` and the organisation root are `legacy` and serve
committed files. Changing either breaks the ontology sites.

## 5. Add a `v*` tag policy to the `github-pages` environment

**This is the step that cost #116 a run.** GitHub creates the `github-pages` environment with a
deployment branch policy that allows the default branch only, so the first tag-triggered deploy
fails in one second with *"Tag v0.1.0 is not allowed to deploy to github-pages due to environment
protection rules."*

Add a deployment branch policy of **type `tag`** with the pattern `v*`, before the first publish.
[#121](https://github.com/EHoffm/kapps_semantic_middleware/issues/121)'s publish-by-tag model is
bitten by the same default in the same way.

## 6. Set `DOCS_BASE_URL`

```bash
gh variable set DOCS_BASE_URL --repo circularfactory/<repo> \
  --body "https://circularfactory.github.io/<repo>"
```

The workflow falls back to this repository's URL when the variable is unset, which silently produces
a `switcher.json` pointing at the wrong site.

## 7. Register the repository on the organisation front door

[#136](https://github.com/EHoffm/kapps_semantic_middleware/issues/136) generates
`circularfactory.github.io` from repository metadata. Three fields, set once:

```bash
gh repo edit circularfactory/<repo> \
  --description "<one sentence, written for a stranger>" \
  --homepage "https://circularfactory.github.io/<repo>/latest/" \
  --add-topic cf-tool
```

**Without the topic the repository does not appear.** Registration is opt-in by design — an
allowlist, the same call #110 made — so a throwaway repository is never advertised on a page aimed
at reviewers.

The `description` is what a reader sees on the front door. Write it for someone arriving from a
paper who has not heard of the project.

## 8. Cut a tag and verify

Confirm all three serve:

- `https://circularfactory.github.io/<repo>/v/<version>/`
- `https://circularfactory.github.io/<repo>/latest/`
- `https://circularfactory.github.io/<repo>/latest/_static/switcher.json`

On the **second** release, also confirm the build log reads `restored <older> from <tag>`. That line
is the archive path working. Without it the older version is gone from the site.

## Traps

**Older versions are restored, never rebuilt.** `deploy-pages` replaces the entire site on every
run. Each release attaches `docs.tar.gz` to its own tag, and the workflow unpacks every prior tag's
archive beside the fresh build. No old tag ever has to keep building against its contemporary
dependencies, so the site cannot rot — but it also means **a deleted release asset deletes that
version of the docs**.

**`latest/` is a copy, not a symlink.** `upload-pages-artifact` does not preserve symlinks reliably,
and a broken `latest` is a broken site.

**The doctree cache must live outside the output tree.** Building without `-d` published the 15M
`.doctrees` cache with the site: 23M per version instead of 8.1M. With `-d`, the archive-per-tag
scheme has roughly 125 releases of headroom under Pages' 1GB limit.

**The interim pin block is load-bearing until #120.** `aas_middleware` is pinned to `14aa60a`,
[#111](https://github.com/EHoffm/kapps_semantic_middleware/issues/111)'s fork point — **not** the
`rest_generalization` tip, which has since moved to `fb4b7a4` and reintroduces the notification
fanout #94 fixed. Anyone re-deriving the pin from "the branch" gets the wrong code. Once
[#120](https://github.com/EHoffm/kapps_semantic_middleware/issues/120) cuts the editable path
sources, the whole block collapses to `pip install .`.

**`-W --keep-going` is on from day one.** #116 reached 0 warnings across 15 reference pages and 14
modules, so a new site starts clean and any warning is new.

**`myst-nb` registers `myst_parser` itself.** Loading both raises *"extension myst_parser is already
registered"*.

## What does not get a site

`transitional-sync-middleware` deliberately gets none.
[#111](https://github.com/EHoffm/kapps_semantic_middleware/issues/111) says it must not be adopted,
and a documentation site is an invitation to adopt.
