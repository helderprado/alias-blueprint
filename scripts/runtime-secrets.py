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


def query_network_policy(component):
    import re
    names = [n.strip() for n in os.environ.get(component.upper() + '_ALLOWED_NAMESPACES', '').split(',') if n.strip()]
    if any(len(n) > 63 or not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', n) for n in names):
        raise ValueError('Allowed namespaces must be comma-separated DNS labels')
    ingress = [{'from': [{'podSelector': {}}]}]
    if names:
        ingress.append({'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': name}}}
                                 for name in sorted(set(names))],
                        'ports': [{'protocol': 'TCP', 'port': port} for port in
                                  ([8443] if component == 'trino' else [9000, 8099])]})
    return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
            'metadata': {'name': component + '-client-access', 'namespace': component},
            'spec': {'podSelector': {}, 'policyTypes': ['Ingress'], 'ingress': ingress}}


def build(component):
    if component == 'spark':
        from spark_runtime import build as build_spark
        return build_spark()
    if component == 'minio':
        from minio_runtime import build as build_minio
        return build_minio()
    secrets = []
    def secret(name, data):
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                        'metadata': {'name': name, 'namespace': component}, 'stringData': data})
    if component == 'trino':
        import re
        from trino_security import material
        shared = required('TRINO_SHARED_SECRET')
        if not re.fullmatch(r'[A-Za-z0-9+/=_-]{32,}', shared):
            raise ValueError('TRINO_SHARED_SECRET must contain at least 32 base64/hex-safe characters')
        directory = material()
        query_network_policy(component)  # Validate before any namespace or Secret write.
        workers = int(os.environ.get('TRINO_WORKERS') or '1')
        if not 1 <= workers <= 100:
            raise ValueError('TRINO_WORKERS must be in 1..100')
        secret('trino-auth', {'password.db': (directory / 'password.db').read_text()})
        secret('trino-runtime', {'TRINO_SHARED_SECRET': shared})
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
            'metadata': {'name': 'trino-tls', 'namespace': component},
            'data': {name: base64.b64encode((directory / name).read_bytes()).decode()
                     for name in ('server-bundle.pem', 'ca.pem')}})
        values = {'server': {'workers': workers}}
        catalog_file = os.environ.get('TRINO_CATALOGS_FILE')
        if catalog_file:
            root = Path(__file__).resolve().parents[1]
            path = Path(catalog_file).expanduser()
            if not path.is_absolute():
                path = root / path
            catalogs = json.loads(path.read_text())
            if not isinstance(catalogs, dict) or not catalogs:
                raise ValueError('TRINO_CATALOGS_FILE must contain a nonempty JSON object of catalog properties')
            data = {}
            for name, properties in catalogs.items():
                if not re.fullmatch(r'[a-z][a-z0-9_-]{0,62}', name) or not isinstance(properties, str) or 'connector.name=' not in properties:
                    raise ValueError('Each catalog needs a valid name and a connector.name property')
                data[name + '.properties'] = properties
            secret('trino-catalogs', data)
            values['additionalConfigProperties'] = ['internal-communication.shared-secret=${ENV:TRINO_SHARED_SECRET}',
                                                   'catalog.config-dir=/etc/trino/secret-catalogs']
            values['secretMounts'] = [
                {'name': 'tls', 'secretName': 'trino-tls', 'path': '/etc/trino/tls'},
                {'name': 'catalogs', 'secretName': 'trino-catalogs', 'path': '/etc/trino/secret-catalogs'}]
        return secrets, values
    if component == 'pinot':
        import re
        query_network_policy(component)
        cluster = os.environ.get('PINOT_CLUSTER_NAME') or 'pinot'
        if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?', cluster):
            raise ValueError('PINOT_CLUSTER_NAME must be a DNS label')
        values = {'cluster': {'name': cluster}}
        url = os.environ.get('PINOT_ZOOKEEPER_URL') or ''
        if url:
            if ':' not in url or any(char.isspace() for char in url) or '@' in url:
                raise ValueError('PINOT_ZOOKEEPER_URL must be a ZooKeeper connection string without embedded credentials')
            values['zookeeper'] = {'enabled': False, 'urlOverride': url}
        storage = os.environ.get('PINOT_STORAGE_CLASS') or ''
        if storage:
            for role in ('controller', 'server', 'zookeeper'):
                values.setdefault(role, {})['persistence'] = {'storageClass': storage}
        return secrets, values
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
        directory, admin, app = material()
        secret('opensearch-security', {name: json.dumps(document) for name, document in
                                       security_documents(directory, admin, app).items()})
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
            secrets[1]['stringData']['search-truststore-password'] = required('OPENMETADATA_SEARCH_TRUSTSTORE_PASSWORD')
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
        repo = os.environ.get('AIRFLOW_DAGS_GIT_REPO') or ''
        commit = os.environ.get('AIRFLOW_DAGS_GIT_REF') or ''
        if repo:
            parsed_repo = urlsplit(repo)
            if parsed_repo.scheme in ('http', 'https') and (parsed_repo.username or parsed_repo.password):
                raise ValueError('DAG Git URL must not contain credentials; use AIRFLOW_GIT_CREDENTIALS_SECRET')
            import re
            if not re.fullmatch(r'[a-fA-F0-9]{40}', commit):
                raise ValueError('AIRFLOW_DAGS_GIT_REF must be an exact 40-character Git commit when a DAG repository is set')
        dags_pvc = os.environ.get('AIRFLOW_DAGS_PVC') or ''
        secret('airflow-fernet', {'fernet-key': fernet})
        secret('airflow-webserver', {'webserver-secret-key': required('AIRFLOW_WEBSERVER_SECRET_KEY')})
        secret('airflow-metadata', {'connection': required('AIRFLOW_DATABASE_URL')})
        return secrets, {'fernetKeySecretName': 'airflow-fernet', 'webserverSecretKeySecretName': 'airflow-webserver',
                         'data': {'metadataSecretName': 'airflow-metadata'}, 'postgresql': {'enabled': False},
                         'dags': {'persistence': {'enabled': bool(dags_pvc), 'existingClaim': dags_pvc or None},
                                  'gitSync': {'enabled': bool(repo), 'repo': repo, 'ref': commit, 'rev': commit,
                                      'subPath': os.environ.get('AIRFLOW_DAGS_SUBPATH') or '',
                                      'credentialsSecret': os.environ.get('AIRFLOW_GIT_CREDENTIALS_SECRET') or None}},
                         'createUserJob': {'useHelmHooks': False, 'applyCustomEnv': False, 'ttlSecondsAfterFinished': 300},
                         'migrateDatabaseJob': {'useHelmHooks': False, 'applyCustomEnv': False, 'ttlSecondsAfterFinished': 300}}
    if component == 'superset':
        mapping = {'SUPERSET_SECRET_KEY': 'SUPERSET_SECRET_KEY', 'DB_USER': 'SUPERSET_DB_USER',
                   'DB_PASS': 'SUPERSET_DB_PASSWORD', 'DB_HOST': 'SUPERSET_DB_HOST',
                   'DB_NAME': 'SUPERSET_DB_NAME', 'REDIS_PASSWORD': 'SUPERSET_REDIS_PASSWORD'}
        secret('superset-runtime', {key: required(var) for key, var in mapping.items()})
        return secrets, {'extraEnvRaw': [ref('superset-runtime', key, key) for key in mapping],
            'supersetNode': {'connections': {'db_host': required('SUPERSET_DB_HOST'),
                'db_user': required('SUPERSET_DB_USER'), 'db_name': required('SUPERSET_DB_NAME')}},
            'redis': {'auth': {'enabled': True, 'existingSecret': 'superset-runtime', 'existingSecretPasswordKey': 'REDIS_PASSWORD'}}}
    raise ValueError('Unknown component')


def main():
    component, output = sys.argv[1:]
    secrets, values = build(component)  # Validate everything before any cluster request.
    if component in ('mlflow', 'openmetadata', 'opensearch', 'airflow', 'trino', 'pinot', 'minio', 'spark'):
        namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': component}}
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(namespace), text=True, check=True)
    if component in ('trino', 'pinot'):
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(query_network_policy(component)), text=True, check=True)
    if not secrets:
        with open(output, 'w') as stream:
            json.dump(values, stream)
        return
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
