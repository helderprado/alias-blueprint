#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime mlflow
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install --values "$SCRIPT_DIR/values.yaml" --namespace mlflow mlflow mlflow --repo https://community-charts.github.io/helm-charts/ --version "$(chart_version mlflow)" --values "$RUNTIME_VALUES" --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" --values "$SCRIPT_DIR/../versions/mlflow.values.json"
