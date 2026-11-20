#!/usr/bin/env python3
"""Validate component inputs, apply external Secrets, emit credential-free Helm JSON."""
import base64
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit


def required(name):
    value = os.environ.get(name, '')
    if not value.strip():
        raise ValueError(f'Missing required variable: {name}')
    return value


def ref(secret, key, name=None):
    value = {'valueFrom': {'secretKeyRef': {'name': secret, 'key': key}}}
    return dict(name=name, **value) if name else value


def build(component):
    secrets = []
    def secret(name, data):
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                        'metadata': {'name': name, 'namespace': component}, 'stringData': data})
    if component == 'jupyterhub':
        crypt = required('JUPYTERHUB_CRYPT_KEY')
        if len(crypt) != 64 or any(c not in '0123456789abcdefABCDEF' for c in crypt):
            raise ValueError('JUPYTERHUB_CRYPT_KEY must be 32 bytes encoded as 64 hex characters')
        secret('jupyterhub-runtime', {'crypt-key': crypt, 'auth-password': required('JUPYTERHUB_AUTH_PASSWORD')})
        return secrets, {}
    if component == 'mlflow':
        secret('mlflow-runtime', {'username': required('MLFLOW_DB_USER'), 'password': required('MLFLOW_DB_PASSWORD'),
                                 'AWS_ACCESS_KEY_ID': required('MLFLOW_S3_ACCESS_KEY_ID'),
                                 'AWS_SECRET_ACCESS_KEY': required('MLFLOW_S3_SECRET_ACCESS_KEY')})
        endpoint = required('MLFLOW_S3_ENDPOINT_URL')
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('MLFLOW_S3_ENDPOINT_URL must be an HTTP(S) endpoint without embedded credentials or query parameters')
        port = int(os.environ.get('MLFLOW_DB_PORT', '3306'))
        if not 1 <= port <= 65535:
            raise ValueError('MLFLOW_DB_PORT must be in 1..65535')
        return secrets, {'backendStore': {'mysql': {'host': required('MLFLOW_DB_HOST'), 'port': port,
            'database': required('MLFLOW_DB_NAME')}, 'existingDatabaseSecret': {'name': 'mlflow-runtime',
            'usernameKey': 'username', 'passwordKey': 'password'}},
            'artifactRoot': {'s3': {'bucket': required('MLFLOW_S3_BUCKET'), 'existingSecret': {
                'name': 'mlflow-runtime', 'keyOfAccessKeyId': 'AWS_ACCESS_KEY_ID', 'keyOfSecretAccessKey': 'AWS_SECRET_ACCESS_KEY'}}},
            'extraEnvVars': {'MLFLOW_S3_ENDPOINT_URL': required('MLFLOW_S3_ENDPOINT_URL'),
                'MLFLOW_ARTIFACT_ROOT': 's3://' + required('MLFLOW_S3_BUCKET') + '/ML_MODELS'}}
    if component == 'airflow':
        fernet = required('AIRFLOW_FERNET_KEY')
        try:
            valid = len(base64.b64decode(fernet, altchars=b'-_', validate=True)) == 32
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError('AIRFLOW_FERNET_KEY must be a URL-safe base64 encoding of 32 bytes')
        secret('airflow-fernet', {'fernet-key': fernet})
        secret('airflow-webserver', {'webserver-secret-key': required('AIRFLOW_WEBSERVER_SECRET_KEY')})
        secret('airflow-metadata', {'connection': required('AIRFLOW_DATABASE_URL')})
        return secrets, {'fernetKeySecretName': 'airflow-fernet', 'webserverSecretKeySecretName': 'airflow-webserver',
                         'data': {'metadataSecretName': 'airflow-metadata'}, 'postgresql': {'enabled': False},
                         'createUserJob': {'useHelmHooks': False, 'applyCustomEnv': False, 'ttlSecondsAfterFinished': 300},
                         'migrateDatabaseJob': {'useHelmHooks': False, 'applyCustomEnv': False, 'ttlSecondsAfterFinished': 300}}
    if component == 'superset':
        mapping = {'SUPERSET_SECRET_KEY': 'SUPERSET_SECRET_KEY', 'DB_USER': 'SUPERSET_DB_USER',
                   'DB_PASS': 'SUPERSET_DB_PASSWORD', 'DB_HOST': 'SUPERSET_DB_HOST',
                   'DB_NAME': 'SUPERSET_DB_NAME', 'REDIS_PASSWORD': 'SUPERSET_REDIS_PASSWORD'}
        secret('superset-runtime', {key: required(var) for key, var in mapping.items()})
        return secrets, {'extraEnvRaw': [ref('superset-runtime', key, key) for key in mapping],
            'redis': {'auth': {'enabled': True, 'existingSecret': 'superset-runtime', 'existingSecretKey': 'REDIS_PASSWORD'}}}
    raise ValueError('Unknown component')


def main():
    component, output = sys.argv[1:]
    secrets, values = build(component)  # Validate everything before any cluster request.
    # External Secrets are outside Helm revision history. Do not change them during
    # an application upgrade: an automatic Helm rollback could not undo that change.
    result = subprocess.run(['kubectl', 'get', 'secret', *[s['metadata']['name'] for s in secrets],
                             '--namespace', component, '--ignore-not-found', '-o', 'json'],
                            capture_output=True, text=True, check=True)
    current = json.loads(result.stdout or '{"items": []}')
    items = current.get('items', [current] if current.get('kind') == 'Secret' else [])
    existing = {s['metadata']['name']: s for s in items}
    missing = []
    for secret in secrets:
        old = existing.get(secret['metadata']['name'])
        if old is None:
            missing.append(secret)
            continue
        for key, value in secret['stringData'].items():
            encoded = base64.b64encode(value.encode()).decode()
            if old.get('data', {}).get(key) != encoded:
                raise ValueError('Existing runtime Secret differs: ' + secret['metadata']['name'] +
                                 '. Credential changes require a separate migration plan; no Secret was modified.')
    if missing:
        payload = json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': missing})
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=payload, text=True, check=True)
    with open(output, 'w') as stream:
        json.dump(values, stream)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('Runtime Secret preparation failed; Helm was not started.', file=sys.stderr)
        sys.exit(1)
