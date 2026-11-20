#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime opensearch
helm upgrade --install opensearch opensearch \
    --repo https://opensearch-project.github.io/helm-charts --version "$(chart_version opensearch)" \
    --namespace opensearch --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
    --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES" \
    --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --values "$SCRIPT_DIR/../versions/opensearch.values.json"
