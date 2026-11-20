#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
ROLE="${1:-}"
if [[ "$#" -ne 1 || ! "$ROLE" =~ ^(server|gateway|client)$ ]]; then
    echo 'Usage: bash glusterfs/install-node.sh server|gateway|client' >&2
    exit 1
fi
if [[ "$EUID" -ne 0 ]]; then
    echo 'Run this host provisioning script as root.' >&2
    exit 1
fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 22.04 || "$(dpkg --print-architecture)" != amd64 ]]; then
    echo 'The package lock targets Ubuntu 22.04 amd64.' >&2
    exit 1
fi
if [[ "$ROLE" == server ]]; then
    python3 "$SCRIPT_DIR/storage.py" validate-volume >/dev/null
    mountpoint -q -- "${GLUSTERFS_BRICK_MOUNT:-/srv/glusterfs}" || {
        echo 'Mount a dedicated brick filesystem before installing the server.' >&2
        exit 1
    }
fi
PACKAGE_TEXT="$(python3 "$SCRIPT_DIR/storage.py" packages "$ROLE")"
mapfile -t PACKAGES <<< "$PACKAGE_TEXT"
for package in "${PACKAGES[@]}"; do
    name="${package%%=*}"
    desired="${package#*=}"
    installed="$(dpkg-query -W -f='${Version}' "$name" 2>/dev/null || true)"
    if [[ -n "$installed" ]] && dpkg --compare-versions "$installed" gt "$desired"; then
        echo "Refusing to downgrade $name from $installed to $desired; review the lock." >&2
        exit 1
    fi
done
apt-get update
apt-get install --yes --no-remove --no-install-recommends "${PACKAGES[@]}"
for package in "${PACKAGES[@]}"; do
    [[ "$(dpkg-query -W -f='${Version}' "${package%%=*}")" == "${package#*=}" ]] || {
        echo "Installed package does not match lock: $package" >&2
        exit 1
    }
done
if [[ "$ROLE" == server ]]; then
    # Keep the brick below the mount root; do not use force on a root filesystem.
    python3 "$SCRIPT_DIR/storage.py" prepare-brick
    systemctl enable --now glusterd
fi
