#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
helm upgrade --install --values "$SCRIPT_DIR/values.yaml" --namespace superset superset superset/superset
