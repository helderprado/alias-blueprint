#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --cleanup-on-fail --install homepage homepage --repo https://jameswynn.github.io/helm-charts/ --version "$(chart_version homepage)" --namespace homepage --values "$SCRIPT_DIR/values.yaml" --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" --values "$SCRIPT_DIR/../versions/homepage.values.json"
