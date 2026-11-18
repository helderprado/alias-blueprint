#!/usr/bin/env bash
set -euo pipefail
: "${1:?Usage: create-pull-secret.sh NAMESPACE}"
export REGISTRY_NAMESPACE="$1"
read -r -p 'Registry server (host:port): ' REGISTRY_SERVER
read -r -p 'Registry username (not admin): ' REGISTRY_USER
if [[ -z "$REGISTRY_SERVER" || -z "$REGISTRY_USER" || "${REGISTRY_USER,,}" == admin ]]; then
    echo 'Provide a registry server and non-admin username.' >&2
    exit 1
fi
read -r -s -p 'Registry password: ' REGISTRY_PASS
printf '\n'
[[ -n "$REGISTRY_PASS" ]] || exit 1
export REGISTRY_SERVER REGISTRY_USER REGISTRY_PASS
python3 - <<'PYTHON' | kubectl apply -f -
import base64, json, os
user, password, server = (os.environ[k] for k in ('REGISTRY_USER', 'REGISTRY_PASS', 'REGISTRY_SERVER'))
auth = base64.b64encode((user + ':' + password).encode()).decode()
config = json.dumps({'auths': {server: {'auth': auth}}}).encode()
print(json.dumps({'apiVersion': 'v1', 'kind': 'Secret',
    'metadata': {'name': 'regcred', 'namespace': os.environ['REGISTRY_NAMESPACE']},
    'type': 'kubernetes.io/dockerconfigjson',
    'data': {'.dockerconfigjson': base64.b64encode(config).decode()}}))
PYTHON
unset REGISTRY_PASS
