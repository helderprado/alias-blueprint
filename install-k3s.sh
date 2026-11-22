#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
    --smoke)
        shift
        exec python3 "$SCRIPT_DIR/scripts/local-smoke.py" --run "$@"
        ;;
    --help|-h)
        echo 'Usage: bash install-k3s.sh [--smoke [smoke options]]'
        echo 'No arguments: install the article K3s service. --smoke: install it, then test Kubernetes components.'
        exit 0
        ;;
    '') [[ $# -eq 0 ]] || exit 1 ;;
    *) echo 'Usage: bash install-k3s.sh [--smoke [smoke options]]' >&2; exit 1 ;;
esac
source "$SCRIPT_DIR/scripts/env.sh"

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
# Execute only a complete download. A failing curl must never run partial shell code.
umask 077
K3S_INSTALLER_FILE="$(mktemp)"
trap 'rm -f -- "$K3S_INSTALLER_FILE"' EXIT
curl --fail --show-error --silent --location --proto '=https' --tlsv1.2 \
    --connect-timeout 15 --max-time 120 --output "$K3S_INSTALLER_FILE" https://get.k3s.io
if [[ ! -s "$K3S_INSTALLER_FILE" ]]; then
    echo 'The downloaded K3s installer is empty.' >&2
    exit 1
fi
sh "$K3S_INSTALLER_FILE" server --cluster-init --config "$K3S_CONFIG"
