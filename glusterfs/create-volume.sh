#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
if [[ "$#" -gt 1 || ( "$#" -eq 1 && "$1" != --render ) ]]; then
    echo 'Usage: bash glusterfs/create-volume.sh [--render]' >&2
    exit 1
fi
if [[ "${1:-}" == --render ]]; then
    exec python3 "$SCRIPT_DIR/storage.py" volume-plan
fi
exec python3 "$SCRIPT_DIR/storage.py" create-volume
