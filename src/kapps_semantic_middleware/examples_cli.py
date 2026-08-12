"""CLI tool to copy bundled example scenarios into a user-writable directory.

This module provides the ``kapps-examples`` console script. It locates the
example files that ship with the package (either from an installed wheel or
from a development checkout) and copies them to a destination the user owns.
The examples are meant to be edited and re-run locally, not executed from
within site-packages.
"""

from __future__ import annotations

import argparse
import importlib.resources as ir
import sys
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

# The exact payload files to copy. Do not add __init__.py, CONTEXT.md, docs/,
# or .ipynb_checkpoints here.
PAYLOAD_FILES: Final[tuple[str, ...]] = (
    "scenario1_hello_world.ipynb",
    "scenario1_hello_world.py",
    "scenario2_door.ipynb",
    "scenario2_door.py",
    "handlers.py",
    "seed.py",
    "demo_scenario1.ttl",
    "demo_scenario2.ttl",
    "transferunit.ttl",
    "demo_handover.ttl",
)

COPIED_README: Final[str] = """# kapps example scenarios

This folder holds copies of the example scenarios that ship with
kapps_semantic_middleware. You own these files -- edit and re-run them freely.
Re-running ``kapps-examples`` will not overwrite them unless you pass ``--force``.

## What is here

- **Scenario 1 (hello-world)**: operation coordination through the semantic graph.
  Available as ``scenario1_hello_world.ipynb`` (Jupyter notebook) and
  ``scenario1_hello_world.py`` (plain script).
- **Scenario 2 (door + mobile robot)**: direct state discovery and control.
  Available as ``scenario2_door.ipynb`` and ``scenario2_door.py``.
- **Supporting files**: ``handlers.py`` (the callbacks the scenarios register),
  ``seed.py`` (clears and seeds the graph), and the ``*.ttl`` ontology/seed data
  the scenarios load.

## Prerequisites

The scenarios need a reachable GraphDB. Set the four ``GRAPHDB_*`` environment
variables to point at your database. For a one-command local database, see the
project README section "Run a local GraphDB (Docker)".

## Run a scenario

Two ways, same result:

1. As a script: ``python scenario1_hello_world.py`` (or ``scenario2_door.py``).
2. In Jupyter: open ``scenario1_hello_world.ipynb`` in Jupyter or JupyterLab.
   Jupyter comes from the notebooks extra: ``pip install "kapps-semantic-middleware[notebooks]"``.

## Run the factory

The TransferUnit factory is not a file in this folder. It runs as an installed
command:

```bash
kapps-transferunit-factory --units 2 --force
```

It serves a live status page on http://127.0.0.1:8080/.
"""


def _locate_examples_root() -> Traversable:
    """Find the bundled examples directory, trying both import names.

    In an installed wheel, the examples live under ``kapps_semantic_middleware.examples``
    (the build remaps them there). In a development checkout, they are importable as the
    top-level ``examples`` package. This tries both and returns the first that resolves and
    actually contains ``seed.py``, so a stray empty namespace package cannot match.
    """
    for pkg in ("kapps_semantic_middleware.examples", "examples"):
        try:
            root = ir.files(pkg)
        except (ModuleNotFoundError, TypeError):
            continue
        if root.joinpath("seed.py").is_file():
            return root
    raise RuntimeError("could not locate the bundled examples")


def copy_examples(dest: Path, *, force: bool = False) -> list[Path]:
    """Copy the bundled example files into a user-writable directory.

    Creates ``dest`` if it does not exist. For each file, an existing target is skipped with a
    warning unless ``force`` is set, so a user's own edits are never clobbered by accident.
    Returns the files actually written (the payload plus the generated ``README.md``); skipped
    files are not included.
    """
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    root = _locate_examples_root()
    written: list[Path] = []

    for name in PAYLOAD_FILES:
        target = dest / name
        if target.exists() and not force:
            print(f"Skipping {name} (already exists; use --force to overwrite)")
            continue
        target.write_bytes(root.joinpath(name).read_bytes())
        written.append(target)

    readme = dest / "README.md"
    if readme.exists() and not force:
        print("Skipping README.md (already exists; use --force to overwrite)")
    else:
        readme.write_text(COPIED_README, encoding="utf-8")
        written.append(readme)

    return written


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``kapps-examples`` console script. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="kapps-examples",
        description="Copy the bundled example scenarios into a local directory you can edit and run.",
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default="./kapps-examples",
        help="Destination directory (default: ./kapps-examples)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files that already exist in the destination",
    )

    args = parser.parse_args(argv)
    dest = Path(args.dest).resolve()

    written = copy_examples(dest, force=args.force)

    print(f"\nCopied {len(written)} file(s) to {dest}")
    print("\nNext steps:")
    print(f"  cd {dest}")
    print("  # point GRAPHDB_* at a reachable GraphDB -- see the repo README,")
    print("  # section 'Run a local GraphDB (Docker)', for a one-command local option")
    print("  python scenario1_hello_world.py        # or scenario2_door.py")
    print("  # or open scenario1_hello_world.ipynb in Jupyter (needs the [notebooks] extra)")
    print("  # the factory is a separate command, not a file here:")
    print("  kapps-transferunit-factory --units 2 --force   # serves http://127.0.0.1:8080/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
