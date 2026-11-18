#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION='v1.34.13+k3s1' sh -s - server --cluster-init --config "$SCRIPT_DIR/k3s-config.yaml"
