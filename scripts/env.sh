#!/usr/bin/env bash
# Source from entrypoints before reading configuration. The optional file is trusted shell syntax.
set +x
ALIAS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ALIAS_ENV_PATH="${ALIAS_ENV_FILE:-$ALIAS_ROOT/.env}"
if [[ -f "$ALIAS_ENV_PATH" ]]; then
    set -a
    source "$ALIAS_ENV_PATH"
    set +a
elif [[ -n "${ALIAS_ENV_FILE:-}" ]]; then
    echo "Environment file not found: $ALIAS_ENV_PATH" >&2
    return 1
fi
