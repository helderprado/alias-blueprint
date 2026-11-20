#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime trino
CHART_DIR="$(mktemp -d)"
trap 'rm -f -- "$RUNTIME_VALUES"; rm -rf -- "$CHART_DIR"' EXIT
helm pull trino --repo https://trinodb.github.io/charts \
    --version "$(chart_version trino)" --destination "$CHART_DIR"
python3 "$ALIAS_ROOT/scripts/prepare-trino-chart.py" \
    "$CHART_DIR/trino-$(chart_version trino).tgz" "$CHART_DIR/pinned.tgz"
helm upgrade --install trino "$CHART_DIR/pinned.tgz" \
    --namespace trino --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
    --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES" \
    --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --values "$SCRIPT_DIR/../versions/trino.values.json"
