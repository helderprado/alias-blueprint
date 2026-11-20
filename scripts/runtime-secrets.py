#!/usr/bin/env python3
"""Validate component inputs, apply external Secrets, emit credential-free Helm JSON."""
import base64
import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path
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
    if component == 'opensearch':
        from opensearch_security import material, security_documents
        directory, admin, catalog = material()
        secret('opensearch-security', {name: json.dumps(document) for name, document in
                                       security_documents(directory, admin, catalog).items()})
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                        'metadata': {'name': 'opensearch-tls', 'namespace': component},
                        'data': {name: base64.b64encode((directory / name).read_bytes()).decode()
                                 for name in ('ca.pem', 'node.pem', 'node-key.pem')}})
        return secrets, {}
    if component == 'openmetadata':
        fernet = required('OPENMETADATA_FERNET_KEY')
        try:
            valid = len(base64.b64decode(fernet, altchars=b'-_', validate=True)) == 32
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError('OPENMETADATA_FERNET_KEY must encode exactly 32 bytes')
        public_url = required('OPENMETADATA_PUBLIC_URL').rstrip('/')
        discovery = required('OPENMETADATA_OIDC_DISCOVERY_URL')
        jwks = required('OPENMETADATA_OIDC_JWKS_URL')
        for url in [public_url, discovery, jwks]:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('OpenMetadata public and OIDC URLs must be HTTP(S) without embedded credentials')
        root = Path(__file__).resolve().parents[1]
        keys = {}
        for key, variable in [('private_key.der', 'OPENMETADATA_JWT_PRIVATE_KEY_FILE'),
                              ('public_key.der', 'OPENMETADATA_JWT_PUBLIC_KEY_FILE')]:
            path = Path(os.environ.get(variable) or str(root / 'openmetadata/runtime-creds' / key)).expanduser()
            if not path.is_absolute():
                path = root / path
            data = path.read_bytes()
            if not data or data[0] != 0x30:
                raise ValueError('Expected a nonempty DER-encoded JWT key file')
            keys[key] = base64.b64encode(data).decode()
        derived = subprocess.run(['openssl', 'pkey', '-inform', 'DER', '-pubout', '-outform', 'DER'],
                                 input=base64.b64decode(keys['private_key.der']), capture_output=True, check=True).stdout
        if derived != base64.b64decode(keys['public_key.der']):
            raise ValueError('OpenMetadata JWT public and private keys do not match')
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                        'metadata': {'name': 'openmetadata-jwt', 'namespace': component}, 'data': keys})
        secret('openmetadata-runtime', {'db-password': required('OPENMETADATA_DB_PASSWORD'),
            'search-password': required('OPENMETADATA_SEARCH_PASSWORD'), 'fernet-key': fernet,
            'oidc-client-id': required('OPENMETADATA_OIDC_CLIENT_ID'),
            'oidc-client-secret': required('OPENMETADATA_OIDC_CLIENT_SECRET')})
        def secret_key(key):
            return {'secretRef': 'openmetadata-runtime', 'secretKey': key}
        db_port = int(os.environ.get('OPENMETADATA_DB_PORT') or '5432')
        search_port = int(os.environ.get('OPENMETADATA_SEARCH_PORT') or '9200')
        if not (1 <= db_port <= 65535 and 1 <= search_port <= 65535):
            raise ValueError('OpenMetadata ports must be in 1..65535')
        scheme = os.environ.get('OPENMETADATA_SEARCH_SCHEME') or 'https'
        if scheme not in ('http', 'https'):
            raise ValueError('OPENMETADATA_SEARCH_SCHEME must be http or https')
        values = {'openmetadata': {'config': {
            'database': {'host': required('OPENMETADATA_DB_HOST'), 'port': db_port,
                'driverClass': 'org.postgresql.Driver', 'dbScheme': 'postgresql',
                'databaseName': required('OPENMETADATA_DB_NAME'),
                'dbParams': os.environ.get('OPENMETADATA_DB_PARAMS') or 'sslmode=require',
                'auth': {'username': required('OPENMETADATA_DB_USER'), 'password': secret_key('db-password')}},
            'elasticsearch': {'host': required('OPENMETADATA_SEARCH_HOST'), 'port': search_port,
                'searchType': 'opensearch', 'scheme': scheme,
                'auth': {'enabled': True, 'username': required('OPENMETADATA_SEARCH_USER'),
                         'password': secret_key('search-password')}},
            'authorizer': {'initialAdmins': [required('OPENMETADATA_ADMIN_PRINCIPAL')],
                           'principalDomain': required('OPENMETADATA_PRINCIPAL_DOMAIN')},
            'authentication': {'publicKeys': [public_url + '/api/v1/system/config/jwks', jwks],
                'authority': required('OPENMETADATA_OIDC_AUTHORITY'),
                'callbackUrl': public_url + '/callback',
                'oidcConfiguration': {'clientId': secret_key('oidc-client-id'),
                    'clientSecret': secret_key('oidc-client-secret'), 'discoveryUri': discovery,
                    'serverUrl': public_url, 'callbackUrl': public_url + '/callback'}},
            'jwtTokenConfiguration': {'jwtissuer': public_url,
                'keyId': hashlib.sha256(base64.b64decode(keys['public_key.der'])).hexdigest()[:32]}}}}
        truststore = os.environ.get('OPENMETADATA_SEARCH_TRUSTSTORE_FILE')
        if truststore:
            path = Path(truststore).expanduser()
            if not path.is_absolute():
                path = root / path
            store = path.read_bytes()
            if not store:
                raise ValueError('OpenMetadata search truststore file is empty')
            secrets[1]['stringData']['search-truststore-password'] = required('OPENSEARCH_TRUSTSTORE_PASSWORD')
            secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': 'openmetadata-search-tls', 'namespace': component},
                'data': {'truststore.jks': base64.b64encode(store).decode()}})
            values['openmetadata']['config']['elasticsearch']['trustStore'] = {
                'enabled': True, 'path': '/opt/openmetadata/search/truststore.jks',
                'password': secret_key('search-truststore-password')}
            values['extraVolumes'] = [
                {'name': 'jwt-keys', 'secret': {'secretName': 'openmetadata-jwt', 'defaultMode': 288}},
                {'name': 'search-ca', 'secret': {'secretName': 'openmetadata-search-tls', 'defaultMode': 288}}]
            values['extraVolumeMounts'] = [
                {'name': 'jwt-keys', 'mountPath': '/opt/openmetadata/jwt', 'readOnly': True},
                {'name': 'search-ca', 'mountPath': '/opt/openmetadata/search', 'readOnly': True}]
        return secrets, values
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
    if component in ('mlflow', 'openmetadata', 'opensearch'):
        namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': component}}
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(namespace), text=True, check=True)
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
        proposed = dict(secret.get('data', {}))
        proposed.update({k: base64.b64encode(v.encode()).decode() for k, v in secret.get('stringData', {}).items()})
        for key, encoded in proposed.items():
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
