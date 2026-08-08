#!/usr/bin/env bash
# Every gate, in the order that fails fastest.
#
# CI runs only the first of these (see .github/workflows/checks.yml): the project cannot be
# installed on a public runner, because `aas_middleware_inf` sits on a private KIT GitLab
# instance. So this script is where mypy and the tests are actually gated. Run it before you
# push.
#
#   scripts/check.sh            lint, types, and the tier that needs no GraphDB
#   scripts/check.sh --live     all of the above plus the live-GraphDB tier
#   scripts/check.sh --smoke    all of the above plus the six-process factory boot
#
# The live and smoke tiers need the GRAPHDB_* variables and a reachable GraphDB. The smoke
# tier also needs the launcher's fixed port free, and it seeds the repository those
# variables point at.

set -euo pipefail

cd "$(dirname "$0")/.."

run() {
    echo
    echo "=== $1 ==="
    shift
    "$@"
}

# Advisory, not a gate. A developer may knowingly work against a drifted sibling checkout
# while chasing a bug across two repositories, and that should not stop them linting. The
# result is repeated in the summary so it cannot scroll past unnoticed.
siblings_ok=yes
echo
echo "=== siblings ==="
python scripts/check_siblings.py || siblings_ok=no

run "ruff" uv run ruff check .
run "mypy" uv run mypy
run "pytest (no GraphDB needed)" uv run pytest -q -m "not live"

for arg in "$@"; do
    case "$arg" in
        --live)
            run "pytest (live GraphDB)" uv run pytest -q
            ;;
        --smoke)
            run "pytest (six-process factory)" uv run pytest -q -m smoke
            ;;
        *)
            echo "unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

echo
echo "All requested gates passed."
if [ "$siblings_ok" = no ]; then
    echo
    echo "WARNING: the sibling checkouts do not match siblings.lock.toml (see above)."
    echo "Everything above passed against the siblings you actually have, which may not be"
    echo "the ones anyone else has. Do not cut a release from this state."
fi
