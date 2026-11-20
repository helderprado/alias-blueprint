#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime superset
helm upgrade --install --values "$SCRIPT_DIR/values.yaml" --namespace superset superset superset/superset --values "$RUNTIME_VALUES"
