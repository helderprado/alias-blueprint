#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime jupyterhub
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --cleanup-on-fail --install jupyterhub jupyterhub --repo https://jupyterhub.github.io/helm-chart/ --version "$(chart_version jupyterhub)" --namespace jupyterhub --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES" --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" --values "$SCRIPT_DIR/../versions/jupyterhub.values.json"
