#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
[[ $# -eq 2 ]] || { echo 'Usage: connection.sh CLIENT NEW_PRIVATE_ENV_FILE' >&2; exit 1; }
python3 "$ALIAS_ROOT/scripts/minio_runtime.py" connection "$1" "$2"
