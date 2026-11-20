#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ $# -eq 1 && "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9./:_-]*:RELEASE\.2025-10-15T17-29-55Z$ ]] || {
    echo 'Usage: build-image.sh REGISTRY/REPOSITORY:RELEASE.2025-10-15T17-29-55Z' >&2
    exit 1
}
DOCKER_BUILDKIT=1 docker build --tag "$1" "$SCRIPT_DIR"
echo 'Image built locally. Publish it deliberately, retain its corresponding-source archive, then configure MINIO_IMAGE with the registry digest.'
