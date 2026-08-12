# Quickstart

:::{warning}
Placeholder. Commands are indicative and are not the release's final wording.
:::

## Install

```bash
pip install kapps-semantic-middleware
```

The examples need more than the library:

```bash
pip install "kapps-semantic-middleware[examples]"
```

## A triple store

Docker is a prerequisite for **running the examples**, never for using the
library.

```bash
docker compose up -d
```

:::{important}
GraphDB must be reachable before the first registration. The `GRAPHDB_*`
environment variables tell the middleware where it is.
:::

## Copy the notebooks out

Notebooks buried in `site-packages` cannot be opened or edited, so a console
command copies them into the working directory.

```bash
kapps-examples copy .
```
