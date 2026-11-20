#!/usr/bin/env bash
set +x
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/env.sh"
: "${1:?Usage: create-pull-secret.sh NAMESPACE}"
: "${REGISTRY_HOST:?Export REGISTRY_HOST (host:port)}"
: "${REGISTRY_USER:?Export REGISTRY_USER for a dedicated registry pull account}"
: "${REGISTRY_PASSWORD:?Export REGISTRY_PASSWORD}"
export REGISTRY_NAMESPACE="$1"
export REGISTRY_SERVICE_ACCOUNT="${REGISTRY_SERVICE_ACCOUNT:-registry-puller}"
export REGISTRY_HOST REGISTRY_USER REGISTRY_PASSWORD
if [[ "${REGISTRY_USER,,}" == admin || "${REGISTRY_USER,,}" == root || "$REGISTRY_USER" == *:* ]]; then
    echo 'Use a dedicated non-administrative registry pull account.' >&2
    exit 1
fi
for value in "$REGISTRY_NAMESPACE" "$REGISTRY_SERVICE_ACCOUNT"; do
    if [[ ${#value} -gt 63 || ! "$value" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
        echo 'Namespace and ServiceAccount must be valid DNS labels.' >&2
        exit 1
    fi
done
for dependency in python3 kubectl; do
    command -v "$dependency" >/dev/null 2>&1 || { echo "Required command not found: $dependency" >&2; exit 1; }
done
python3 - <<'PYTHON' | kubectl apply -f -
import base64, json, os
user, password, server = (os.environ[k] for k in ('REGISTRY_USER', 'REGISTRY_PASSWORD', 'REGISTRY_HOST'))
auth = base64.b64encode((user + ':' + password).encode()).decode()
config = json.dumps({'auths': {server: {'auth': auth}}}).encode()
namespace = os.environ['REGISTRY_NAMESPACE']
secret = {'apiVersion': 'v1', 'kind': 'Secret',
    'metadata': {'name': 'regcred', 'namespace': namespace},
    'type': 'kubernetes.io/dockerconfigjson',
    'data': {'.dockerconfigjson': base64.b64encode(config).decode()}}
account = {'apiVersion': 'v1', 'kind': 'ServiceAccount',
    'metadata': {'name': os.environ['REGISTRY_SERVICE_ACCOUNT'], 'namespace': namespace},
    'automountServiceAccountToken': False, 'imagePullSecrets': [{'name': 'regcred'}]}
print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': [secret, account]}))
PYTHON
unset REGISTRY_PASSWORD
