#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime superset
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install --values "$SCRIPT_DIR/values.yaml" --namespace superset superset superset --repo https://apache.github.io/superset/ --version "$(chart_version superset)" --values "$RUNTIME_VALUES" --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" --values "$SCRIPT_DIR/../versions/superset.values.json"
