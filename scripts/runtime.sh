#!/usr/bin/env bash
# Source after env.sh; caller owns the EXIT trap and temporary values file.
prepare_runtime() {
    for dependency in python3 kubectl helm; do
        command -v "$dependency" >/dev/null 2>&1 || { echo "Required command not found: $dependency" >&2; return 1; }
    done
    umask 077
    RUNTIME_VALUES="$(mktemp)"
    trap 'rm -f -- "$RUNTIME_VALUES"' EXIT
    python3 "$ALIAS_ROOT/scripts/runtime-secrets.py" "$1" "$RUNTIME_VALUES"
}
