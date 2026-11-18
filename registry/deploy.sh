#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AUTH_FILE="$SCRIPT_DIR/registry-creds/htpasswd"
if [[ ! -s "$AUTH_FILE" ]]; then
    echo 'Run registry/gen-pass.sh to generate new local credentials first.' >&2
    exit 1
fi
if grep -qi '^admin:' "$AUTH_FILE"; then
    echo 'Replace the admin account using registry/gen-pass.sh first.' >&2
    exit 1
fi
helm upgrade --install docker-registry twuni/docker-registry --namespace docker-registry \
    --values "$SCRIPT_DIR/values.yaml" --set-file "secrets.htpasswd=$AUTH_FILE"
