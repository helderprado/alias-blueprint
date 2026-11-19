#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Use a fixed release by default; overrides must also name an exact release.
K3S_VERSION="${K3S_VERSION:-${INSTALL_K3S_VERSION:-v1.34.13+k3s1}}"
K3S_CONFIG="${K3S_CONFIG:-$SCRIPT_DIR/k3s-config.yaml}"

if [[ ! "$K3S_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+\+k3s[0-9]+$ ]]; then
    echo 'K3S_VERSION must be an exact release, for example v1.34.13+k3s1.' >&2
    exit 1
fi
if [[ ! -f "$K3S_CONFIG" || ! -r "$K3S_CONFIG" || ! -s "$K3S_CONFIG" ]]; then
    echo "K3S_CONFIG must point to a readable, nonempty configuration file: $K3S_CONFIG" >&2
    exit 1
fi
for dependency in curl sh; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "Required command not found: $dependency" >&2
        exit 1
    fi
done

export INSTALL_K3S_VERSION="$K3S_VERSION"
curl -sfL https://get.k3s.io | sh -s - server --cluster-init --config "$K3S_CONFIG"
