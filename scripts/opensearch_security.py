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
         'admin.hash', 'identity.json')


def required(name):
    value = os.environ.get(name, '')
    if not value.strip():
        raise ValueError('Missing required variable: ' + name)
    return value


def inputs():
    admin = os.environ.get('OPENSEARCH_ADMIN_USER') or 'search-admin'
    app = os.environ.get('OPENSEARCH_APP_USER') or None
    for user in (admin, app):
        if user and not re.fullmatch(r'[a-z][a-z0-9_-]{2,62}', user):
            raise ValueError('OpenSearch usernames must be lowercase labels of 3..63 characters')
    if admin == app:
        raise ValueError('The application account must differ from the administrative account')
    if bool(app) != bool(os.environ.get('OPENSEARCH_APP_PASSWORD')):
        raise ValueError('Set both OPENSEARCH_APP_USER and OPENSEARCH_APP_PASSWORD, or leave both empty')
    names = ['OPENSEARCH_ADMIN_PASSWORD', 'OPENSEARCH_TRUSTSTORE_PASSWORD']
    if app:
        names.append('OPENSEARCH_APP_PASSWORD')
    passwords = {}
    for name in names:
        value = required(name)
        if not 16 <= len(value.encode()) <= 72:
            raise ValueError(name + ' must contain 16..72 UTF-8 bytes')
        passwords[name] = value
    patterns = [p.strip() for p in (os.environ.get('OPENSEARCH_APP_INDEX_PATTERNS') or 'app-*').split(',')] if app else []
    if any(not re.fullmatch(r'[a-z0-9_*?.-]+', p) for p in patterns):
        raise ValueError('OPENSEARCH_APP_INDEX_PATTERNS must be comma-separated index patterns')
    return admin, app, passwords, patterns


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def material():
    admin, app, passwords, patterns = inputs()
    directory = ROOT / 'opensearch/runtime-creds'
    if not all((directory / file).is_file() for file in FILES):
        raise ValueError('Run bash opensearch/gen-security.sh first; local security material is incomplete')
    identity = json.loads((directory / 'identity.json').read_text())
    # Preserve credentials created by the earlier catalog-specific bootstrap.
    old_app = identity.get('app', identity.get('catalog'))
    old_patterns = identity.get('index_patterns', ['*'] if old_app else [])
    if identity.get('admin') != admin or old_app != app or old_patterns != patterns:
        raise ValueError('Existing OpenSearch identities or scopes differ; map OPENSEARCH_APP_* to the existing account before deploying')
    checks = [('admin.hash', 'OPENSEARCH_ADMIN_PASSWORD')]
    if app:
        filename = 'app.hash' if (directory / 'app.hash').is_file() else 'catalog.hash'
        checks.append((filename, 'OPENSEARCH_APP_PASSWORD'))
    for file, name in checks:
        if not (directory / file).is_file() or not bcrypt.checkpw(passwords[name].encode(), (directory / file).read_bytes().strip()):
            raise ValueError('Existing OpenSearch credential differs: ' + name)
    command(['keytool', '-list', '-keystore', str(directory / 'truststore.jks'),
             '-storetype', 'JKS', '-storepass:env', 'OPENSEARCH_TRUSTSTORE_PASSWORD'])
    command(['openssl', 'verify', '-CAfile', str(directory / 'ca.pem'), str(directory / 'node.pem')])
    return directory, admin, app


def bootstrap():
    admin, app, passwords, patterns = inputs()
    for tool in ('openssl', 'keytool'):
        if not shutil.which(tool):
            raise ValueError('Required command not found: ' + tool)
    directory = ROOT / 'opensearch/runtime-creds'
    if any((directory / file).exists() for file in FILES + ('app.hash', 'catalog.hash')):
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
        if app:
            (tmp / 'app.hash').write_bytes(bcrypt.hashpw(passwords['OPENSEARCH_APP_PASSWORD'].encode(), bcrypt.gensalt(12)))
        (tmp / 'identity.json').write_text(json.dumps({'admin': admin, 'app': app, 'index_patterns': patterns}))
        for file in FILES + (('app.hash',) if app else ()):
            (tmp / file).chmod(0o600)
            (tmp / file).replace(directory / file)
    material()


def security_documents(directory, admin, app):
    def meta(kind):
        return {'type': kind, 'config_version': 2}
    users = {'_meta': meta('internalusers'),
             admin: {'hash': (directory / 'admin.hash').read_text(), 'reserved': False, 'backend_roles': ['search_admin']}}
    roles = {'_meta': meta('roles'),
             'bootstrap_admin': {'reserved': True, 'cluster_permissions': ['*'],
                 'index_permissions': [{'index_patterns': ['*'], 'allowed_actions': ['*']}],
                 'tenant_permissions': [{'tenant_patterns': ['*'], 'allowed_actions': ['kibana_all_write']}]}}
    mappings = {'_meta': meta('rolesmapping'),
                'bootstrap_admin': {'reserved': True, 'backend_roles': ['search_admin']}}
    if app:
        identity = json.loads((directory / 'identity.json').read_text())
        legacy = 'catalog' in identity
        role = 'catalog_indexes' if legacy else 'application_indexes'
        backend = 'catalog_indexer' if legacy else 'application_user'
        hash_file = directory / ('app.hash' if (directory / 'app.hash').is_file() else 'catalog.hash')
        users[app] = {'hash': hash_file.read_text(), 'reserved': False, 'backend_roles': [backend]}
        roles[role] = {'reserved': True, 'cluster_permissions': ['cluster_composite_ops', 'cluster_monitor'] + (['indices:admin/template/*'] if identity.get('index_patterns', ['*']) == ['*'] else []),
            'index_permissions': [{'index_patterns': identity.get('index_patterns', ['*']), 'allowed_actions': ['indices_all']}]}
        mappings[role] = {'reserved': True, 'backend_roles': [backend]}
    return {
        'config.yml': {'_meta': meta('config'), 'config': {'dynamic': {
            'http': {'anonymous_auth_enabled': False}, 'authc': {'basic_internal_auth_domain': {
                'http_enabled': True, 'transport_enabled': True, 'order': 0,
                'http_authenticator': {'type': 'basic', 'challenge': True},
                'authentication_backend': {'type': 'intern'}}}}}},
        'internal_users.yml': users, 'roles.yml': roles, 'roles_mapping.yml': mappings,
    }


if __name__ == '__main__':
    try:
        bootstrap()
        print('OpenSearch local security material ready; existing material preserved.')
    except (ValueError, OSError, subprocess.CalledProcessError):
        import sys
        print('OpenSearch bootstrap failed. Check required environment values, tools and existing material; nothing was deployed.', file=sys.stderr)
        sys.exit(1)
