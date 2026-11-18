#!/usr/bin/env bash
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DESTINATION_FOLDER="$SCRIPT_DIR/registry-creds"
read -r -p 'Registry username (not admin): ' REGISTRY_USER
if [[ ! "$REGISTRY_USER" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ || "${REGISTRY_USER,,}" == admin ]]; then
    echo 'Choose a non-admin username using letters, digits, dot, underscore or hyphen.' >&2
    exit 1
fi
read -r -s -p 'New registry password: ' REGISTRY_PASS
printf '\n'
if [[ ${#REGISTRY_PASS} -lt 16 ]]; then
    echo 'Use a new password of at least 16 characters.' >&2
    exit 1
fi
mkdir -p "$DESTINATION_FOLDER"
chmod 700 "$DESTINATION_FOLDER"
TEMP_FILE="$(mktemp "$DESTINATION_FOLDER/.htpasswd.XXXXXX")"
trap 'rm -f -- "$TEMP_FILE"' EXIT
printf '%s\n' "$REGISTRY_PASS" | docker run --rm -i --entrypoint htpasswd httpd:2.4-alpine -Bni "$REGISTRY_USER" > "$TEMP_FILE"
unset REGISTRY_PASS
mv -- "$TEMP_FILE" "$DESTINATION_FOLDER/htpasswd"
echo 'Local authentication file generated. Run registry/deploy.sh to apply it.'
