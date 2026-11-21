#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
case "${1:-}" in
    --render) [[ $# -eq 1 ]]; exec python3 "$ALIAS_ROOT/scripts/spark_runtime.py" resources ;;
    '') [[ $# -eq 0 ]]; exec python3 "$ALIAS_ROOT/scripts/spark_runtime.py" setup ;;
    *) echo 'Usage: setup.sh [--render]' >&2; exit 1 ;;
esac
