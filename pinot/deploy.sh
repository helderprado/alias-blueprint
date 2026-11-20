#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime pinot
helm upgrade --install pinot pinot \
    --repo https://raw.githubusercontent.com/apache/pinot/master/helm --version "$(chart_version pinot)" \
    --namespace pinot --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
    --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES" \
    --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --values "$SCRIPT_DIR/../versions/pinot.values.json"
