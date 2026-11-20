#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DESTINATION="$SCRIPT_DIR/runtime-creds"
if [[ -f "$DESTINATION/private_key.der" && -f "$DESTINATION/public_key.der" ]]; then
    echo 'Existing JWT keys preserved.'
    exit 0
fi
if [[ -e "$DESTINATION/private_key.der" || -e "$DESTINATION/public_key.der" ]]; then
    echo 'Incomplete existing key pair; restore its matching pair before proceeding.' >&2
    exit 1
fi
command -v openssl >/dev/null 2>&1 || { echo 'Required command not found: openssl' >&2; exit 1; }
if [[ -e "$SCRIPT_DIR/../.git" ]]; then
    if [[ -n "$(git -C "$SCRIPT_DIR/.." ls-files -- openmetadata/runtime-creds/)" ]] ||
       ! git -C "$SCRIPT_DIR/.." check-ignore -q -- openmetadata/runtime-creds/private_key.der; then
        echo 'JWT output directory must be ignored and contain no tracked files.' >&2
        exit 1
    fi
fi
mkdir -p "$DESTINATION"
chmod 700 "$DESTINATION"
TEMP_DIR="$(mktemp -d "$DESTINATION/.keys.XXXXXX")"
trap 'rm -rf -- "$TEMP_DIR"' EXIT
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$TEMP_DIR/private.pem" 2>/dev/null
openssl pkcs8 -topk8 -nocrypt -in "$TEMP_DIR/private.pem" -outform DER -out "$TEMP_DIR/private_key.der"
openssl pkey -in "$TEMP_DIR/private.pem" -pubout -outform DER -out "$TEMP_DIR/public_key.der"
mv -- "$TEMP_DIR/private_key.der" "$DESTINATION/private_key.der"
mv -- "$TEMP_DIR/public_key.der" "$DESTINATION/public_key.der"
echo 'JWT keys generated under ignored openmetadata/runtime-creds/.'
