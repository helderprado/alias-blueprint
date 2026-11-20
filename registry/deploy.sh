#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/versions.sh"
source "$SCRIPT_DIR/../scripts/env.sh"
AUTH_FILE="$SCRIPT_DIR/registry-creds/htpasswd"
if [[ ! -s "$AUTH_FILE" ]]; then
    echo 'Run registry/gen-pass.sh to generate new local credentials first.' >&2
    exit 1
fi
if grep -qi '^admin:' "$AUTH_FILE"; then
    echo 'Replace the admin account using registry/gen-pass.sh first.' >&2
    exit 1
fi
helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install docker-registry docker-registry --repo https://twuni.github.io/docker-registry.helm/ --version "$(chart_version registry)" --namespace docker-registry --post-renderer "$SCRIPT_DIR/../scripts/locked-images.py" \
    --values "$SCRIPT_DIR/values.yaml" --set-file "secrets.htpasswd=$AUTH_FILE" --values "$SCRIPT_DIR/../versions/registry.values.json"
