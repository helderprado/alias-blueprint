#!/usr/bin/env bash
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
DESTINATION_FOLDER="$SCRIPT_DIR/registry-creds"
: "${REGISTRY_USER:?Set REGISTRY_USER in .env or export it}"
: "${REGISTRY_PASSWORD:?Set REGISTRY_PASSWORD in .env or export it}"
REGISTRY_PASS="$REGISTRY_PASSWORD"
if [[ ! "$REGISTRY_USER" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ || "${REGISTRY_USER,,}" == admin || "${REGISTRY_USER,,}" == root ]]; then
    echo 'Choose a non-admin username using letters, digits, dot, underscore or hyphen.' >&2
    exit 1
fi
if [[ ${#REGISTRY_PASS} -lt 16 ]]; then
    echo 'Use a new password of at least 16 characters.' >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo 'Required command not found: docker' >&2
    exit 1
fi
# In a checkout, refuse to write authentication material unless Git excludes it.
# Distribution archives have no .git and still use the same local-only directory.
if [[ -e "$ALIAS_ROOT/.git" ]]; then
    command -v git >/dev/null 2>&1 || { echo 'Required command not found: git' >&2; exit 1; }
    if [[ -n "$(git -C "$ALIAS_ROOT" ls-files -- registry/registry-creds/)" ]] ||
       ! git -C "$ALIAS_ROOT" check-ignore -q -- registry/registry-creds/htpasswd; then
        echo 'Credential output must be ignored by Git and contain no tracked files.' >&2
        exit 1
    fi
fi
mkdir -p "$DESTINATION_FOLDER"
chmod 700 "$DESTINATION_FOLDER"
TEMP_FILE="$(mktemp "$DESTINATION_FOLDER/.htpasswd.XXXXXX")"
trap 'rm -f -- "$TEMP_FILE"' EXIT
printf '%s\n' "$REGISTRY_PASS" | docker run --rm -i --entrypoint htpasswd httpd@sha256:32bd0639bcc4917ef1fd9363a1d9dd2dd9c498565118b062a10d51e43a5c3a24 -Bni "$REGISTRY_USER" > "$TEMP_FILE"
unset REGISTRY_PASS REGISTRY_PASSWORD
if [[ ! -s "$TEMP_FILE" ]]; then
    echo 'Credential generation produced no authentication data.' >&2
    exit 1
fi
mv -- "$TEMP_FILE" "$DESTINATION_FOLDER/htpasswd"
echo 'Local authentication file generated. Run registry/deploy.sh to apply it.'
