#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime openmetadata
CHART_DIR="$(mktemp -d)"
trap 'rm -f -- "$RUNTIME_VALUES"; rm -rf -- "$CHART_DIR"' EXIT
helm pull openmetadata --repo https://helm.open-metadata.org \
    --version "$(chart_version openmetadata)" --destination "$CHART_DIR"
python3 "$ALIAS_ROOT/scripts/prepare-openmetadata-chart.py" \
    "$CHART_DIR/openmetadata-$(chart_version openmetadata).tgz" "$CHART_DIR/pinned.tgz"
helm upgrade --install openmetadata "$CHART_DIR/pinned.tgz" \
    --namespace openmetadata --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
    --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES" \
    --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --values "$SCRIPT_DIR/../versions/openmetadata.values.json"
