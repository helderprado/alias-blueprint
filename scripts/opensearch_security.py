"""Local OpenSearch bootstrap material; no cluster access and no plaintext files."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import bcrypt

ROOT = Path(__file__).resolve().parents[1]
FILES = ('ca.pem', 'ca-key.pem', 'node.pem', 'node-key.pem', 'truststore.jks',
         'admin.hash', 'catalog.hash', 'identity.json')


def required(name):
    value = os.environ.get(name, '')
    if not value.strip():
        raise ValueError('Missing required variable: ' + name)
    return value


def inputs():
    admin = os.environ.get('OPENSEARCH_ADMIN_USER') or 'search-admin'
    catalog = required('OPENMETADATA_SEARCH_USER')
    for user in (admin, catalog):
        if not re.fullmatch(r'[a-z][a-z0-9_-]{2,62}', user):
            raise ValueError('OpenSearch usernames must be lowercase labels of 3..63 characters')
    if admin == catalog:
        raise ValueError('OpenMetadata must not use the OpenSearch administrative account')
    passwords = {}
    for name in ('OPENSEARCH_ADMIN_PASSWORD', 'OPENMETADATA_SEARCH_PASSWORD', 'OPENSEARCH_TRUSTSTORE_PASSWORD'):
        value = required(name)
        if not 16 <= len(value.encode()) <= 72:
            raise ValueError(name + ' must contain 16..72 UTF-8 bytes')
        passwords[name] = value
    return admin, catalog, passwords


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def material():
    admin, catalog, passwords = inputs()
    directory = ROOT / 'opensearch/runtime-creds'
    if not all((directory / file).is_file() for file in FILES):
        raise ValueError('Run bash opensearch/gen-security.sh first; local security material is incomplete')
    identity = json.loads((directory / 'identity.json').read_text())
    if identity != {'admin': admin, 'catalog': catalog}:
        raise ValueError('Existing OpenSearch identities differ; use a separate migration plan')
    for file, name in [('admin.hash', 'OPENSEARCH_ADMIN_PASSWORD'), ('catalog.hash', 'OPENMETADATA_SEARCH_PASSWORD')]:
        if not bcrypt.checkpw(passwords[name].encode(), (directory / file).read_bytes().strip()):
            raise ValueError('Existing OpenSearch credential differs: ' + name)
    command(['keytool', '-list', '-keystore', str(directory / 'truststore.jks'),
             '-storetype', 'JKS', '-storepass:env', 'OPENSEARCH_TRUSTSTORE_PASSWORD'])
    command(['openssl', 'verify', '-CAfile', str(directory / 'ca.pem'), str(directory / 'node.pem')])
    return directory, admin, catalog


def bootstrap():
    admin, catalog, passwords = inputs()
    for tool in ('openssl', 'keytool'):
        if not shutil.which(tool):
            raise ValueError('Required command not found: ' + tool)
    directory = ROOT / 'opensearch/runtime-creds'
    if any((directory / file).exists() for file in FILES):
        material()  # Preserve existing keys, hashes and truststore unchanged.
        return
    if (ROOT / '.git').exists():
        tracked = command(['git', '-C', str(ROOT), 'ls-files', '--', 'opensearch/runtime-creds/']).stdout
        if tracked:
            raise ValueError('OpenSearch bootstrap output must not be tracked by Git')
        command(['git', '-C', str(ROOT), 'check-ignore', '-q', '--', 'opensearch/runtime-creds/node-key.pem'])
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='.security-', dir=directory) as name:
        tmp = Path(name)
        command(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes', '-days', '3650',
                 '-keyout', str(tmp / 'ca-key.pem'), '-out', str(tmp / 'ca.pem'), '-subj', '/CN=ALIAS-OpenSearch-CA'])
        command(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(tmp / 'node-key.pem')])
        command(['openssl', 'req', '-new', '-key', str(tmp / 'node-key.pem'), '-out', str(tmp / 'node.csr'), '-subj', '/CN=opensearch-node'])
        names = ['opensearch', 'opensearch.opensearch', 'opensearch.opensearch.svc',
                 'opensearch.opensearch.svc.cluster.local', 'opensearch-headless',
                 '*.opensearch-headless.opensearch.svc.cluster.local',
                 '*.opensearch-headless.opensearch.svc', '*.opensearch-headless', 'localhost']
        (tmp / 'extensions.cnf').write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=serverAuth,clientAuth\nsubjectAltName=' + ','.join('DNS:' + n for n in names) + ',IP:127.0.0.1\n')
        command(['openssl', 'x509', '-req', '-in', str(tmp / 'node.csr'), '-CA', str(tmp / 'ca.pem'),
                 '-CAkey', str(tmp / 'ca-key.pem'), '-CAcreateserial', '-days', '825', '-sha256',
                 '-extfile', str(tmp / 'extensions.cnf'), '-out', str(tmp / 'node.pem')])
        command(['keytool', '-importcert', '-noprompt', '-alias', 'alias-opensearch-ca', '-file', str(tmp / 'ca.pem'),
                 '-keystore', str(tmp / 'truststore.jks'), '-storetype', 'JKS', '-storepass:env', 'OPENSEARCH_TRUSTSTORE_PASSWORD'])
        (tmp / 'admin.hash').write_bytes(bcrypt.hashpw(passwords['OPENSEARCH_ADMIN_PASSWORD'].encode(), bcrypt.gensalt(12)))
        (tmp / 'catalog.hash').write_bytes(bcrypt.hashpw(passwords['OPENMETADATA_SEARCH_PASSWORD'].encode(), bcrypt.gensalt(12)))
        (tmp / 'identity.json').write_text(json.dumps({'admin': admin, 'catalog': catalog}))
        for file in FILES:
            (tmp / file).chmod(0o600)
            (tmp / file).replace(directory / file)
    material()


def security_documents(directory, admin, catalog):
    def meta(kind):
        return {'type': kind, 'config_version': 2}
    return {
        'config.yml': {'_meta': meta('config'), 'config': {'dynamic': {
            'http': {'anonymous_auth_enabled': False}, 'authc': {'basic_internal_auth_domain': {
                'http_enabled': True, 'transport_enabled': True, 'order': 0,
                'http_authenticator': {'type': 'basic', 'challenge': True},
                'authentication_backend': {'type': 'intern'}}}}}},
        'internal_users.yml': {'_meta': meta('internalusers'),
            admin: {'hash': (directory / 'admin.hash').read_text(), 'reserved': True, 'backend_roles': ['search_admin']},
            catalog: {'hash': (directory / 'catalog.hash').read_text(), 'reserved': True, 'backend_roles': ['catalog_indexer']}},
        'roles.yml': {'_meta': meta('roles'),
            'bootstrap_admin': {'reserved': True, 'cluster_permissions': ['*'],
                'index_permissions': [{'index_patterns': ['*'], 'allowed_actions': ['*']}],
                'tenant_permissions': [{'tenant_patterns': ['*'], 'allowed_actions': ['kibana_all_write']}]},
            'catalog_indexes': {'reserved': True, 'cluster_permissions': ['cluster_composite_ops', 'cluster_monitor', 'indices:admin/template/*'],
                'index_permissions': [{'index_patterns': ['*'], 'allowed_actions': ['indices_all']}]}},
        'roles_mapping.yml': {'_meta': meta('rolesmapping'),
            'bootstrap_admin': {'reserved': True, 'backend_roles': ['search_admin']},
            'catalog_indexes': {'reserved': True, 'backend_roles': ['catalog_indexer']}},
    }


if __name__ == '__main__':
    try:
        bootstrap()
        print('OpenSearch local security material ready; existing material preserved.')
    except (ValueError, OSError, subprocess.CalledProcessError):
        import sys
        print('OpenSearch bootstrap failed. Check required environment values, tools and existing material; nothing was deployed.', file=sys.stderr)
        sys.exit(1)
