#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$SCRIPT_DIR/../scripts/versions.sh"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --render ) ]] || { echo 'Usage: deploy.sh [--render]' >&2; exit 1; }
# Validate the selected workload profile before any download or cluster operation.
bash "$SCRIPT_DIR/../spark/setup.sh" --render >/dev/null
if [[ -n "${SPARK_OPERATOR_CHART:-}" ]]; then
    CHART_ARCHIVE="$SPARK_OPERATOR_CHART"
else
    CHART_DIR="$(mktemp -d)"
    trap 'rm -rf -- "$CHART_DIR"' EXIT
    helm pull spark-operator --repo https://kubeflow.github.io/spark-operator/ \
        --version "$(chart_version spark-operator)" --destination "$CHART_DIR"
    CHART_ARCHIVE="$CHART_DIR/spark-operator-$(chart_version spark-operator).tgz"
fi
python3 "$ALIAS_ROOT/scripts/spark_runtime.py" verify-chart "$CHART_ARCHIVE"
if [[ "${1:-}" == --render ]]; then
    helm template spark-operator "$CHART_ARCHIVE" --namespace spark-operator \
        --values "$SCRIPT_DIR/values.yaml" --values "$SCRIPT_DIR/../versions/spark-operator.values.json" \
        --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py"
else
    # Prepare the watched namespace/RBAC before cross-namespace admission setup.
    bash "$SCRIPT_DIR/../spark/setup.sh"
    helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
        --install spark-operator "$CHART_ARCHIVE" --namespace spark-operator --create-namespace \
        --values "$SCRIPT_DIR/values.yaml" --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
        --values "$SCRIPT_DIR/../versions/spark-operator.values.json"
fi
