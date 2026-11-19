#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
kubectl delete -f "$SCRIPT_DIR/service.yaml"
kubectl delete -f "$SCRIPT_DIR/deployment.yaml"
kubectl delete -f "$SCRIPT_DIR/secret.yaml"
