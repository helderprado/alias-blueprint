#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"

source "$SCRIPT_DIR/../scripts/versions.sh"
AIRFLOW_CHART_VERSION="${AIRFLOW_CHART_VERSION:-$(chart_version airflow)}"
AIRFLOW_VALUES="${AIRFLOW_VALUES:-$SCRIPT_DIR/values.yaml}"
if [[ ! "$AIRFLOW_CHART_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'AIRFLOW_CHART_VERSION must name an exact stable release, for example 1.16.0.' >&2
    exit 1
fi
if [[ ! -f "$AIRFLOW_VALUES" || ! -r "$AIRFLOW_VALUES" || ! -s "$AIRFLOW_VALUES" ]]; then
    echo "AIRFLOW_VALUES must point to a readable, nonempty values file: $AIRFLOW_VALUES" >&2
    exit 1
fi
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime airflow
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install airflow airflow --repo https://airflow.apache.org --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --version "$AIRFLOW_CHART_VERSION" --namespace airflow --values "$AIRFLOW_VALUES" --values "$RUNTIME_VALUES" --values "$SCRIPT_DIR/../versions/airflow.values.json"
