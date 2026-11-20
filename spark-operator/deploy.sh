#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install spark-operator spark-operator --repo https://kubeflow.github.io/spark-operator/ --version "$(chart_version spark-operator)" --namespace spark-operator --create-namespace --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" --values "$SCRIPT_DIR/../versions/spark-operator.values.json"
