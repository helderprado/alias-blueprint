#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime mlflow
helm upgrade --install --values "$SCRIPT_DIR/values.yaml" --namespace mlflow mlflow community-charts/mlflow --values "$RUNTIME_VALUES"
