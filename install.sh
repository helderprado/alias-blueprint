#!/usr/bin/env bash
# Local, disposable installation and functional verification; never uses host kubeconfig.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/scripts/local-smoke.py" "$@"
