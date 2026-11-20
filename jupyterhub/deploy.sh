#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
prepare_runtime jupyterhub
helm upgrade --cleanup-on-fail --install jupyterhub jupyterhub/jupyterhub --namespace jupyterhub --values "$SCRIPT_DIR/values.yaml" --values "$RUNTIME_VALUES"
