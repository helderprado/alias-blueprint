#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Compatibility entrypoint: workload permissions now live in namespace spark.
exec bash "$SCRIPT_DIR/../spark/setup.sh" "$@"
