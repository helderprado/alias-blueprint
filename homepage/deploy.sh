#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
helm upgrade --cleanup-on-fail --install homepage jameswynn/homepage --namespace homepage --values "$SCRIPT_DIR/values.yaml"
