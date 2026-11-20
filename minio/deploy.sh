#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
source "$ALIAS_ROOT/scripts/runtime.sh"
case "${1:-}" in
    --render)
        [[ $# -eq 1 ]] || { echo 'Usage: deploy.sh [--render]' >&2; exit 1; }
        umask 077
        RUNTIME_VALUES="$(mktemp)"
        trap 'rm -f -- "$RUNTIME_VALUES"' EXIT
        python3 "$ALIAS_ROOT/scripts/minio_runtime.py" values > "$RUNTIME_VALUES"
        helm template minio "$SCRIPT_DIR/chart" --namespace minio \
            --values "$RUNTIME_VALUES" --post-renderer "$ALIAS_ROOT/scripts/locked-images.py"
        ;;
    '')
        [[ $# -eq 0 ]] || { echo 'Usage: deploy.sh [--render]' >&2; exit 1; }
        python3 "$ALIAS_ROOT/scripts/minio_runtime.py" preflight
        prepare_runtime minio
        helm upgrade --install minio "$SCRIPT_DIR/chart" --namespace minio \
            --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 \
            --values "$RUNTIME_VALUES" --post-renderer "$ALIAS_ROOT/scripts/locked-images.py"
        ;;
    *) echo 'Usage: deploy.sh [--render]' >&2; exit 1 ;;
esac
