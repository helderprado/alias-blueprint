"""Focused offline check of search bootstrap and the catalog's TLS wiring."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import opensearch_security as security
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class OpenSearchTests(unittest.TestCase):
    def test_bootstrap_roles_and_catalog_tls(self):
        with tempfile.TemporaryDirectory(prefix='alias-search-') as name:
            directory = Path(name)
            env = {'OPENSEARCH_ADMIN_USER': 'search-admin', 'OPENSEARCH_ADMIN_PASSWORD': 'Synthetic-Admin-Value-123',
                   'OPENMETADATA_SEARCH_USER': 'catalog-indexer', 'OPENMETADATA_SEARCH_PASSWORD': 'Synthetic-Catalog-Value-123',
                   'OPENSEARCH_TRUSTSTORE_PASSWORD': 'Synthetic-Trust-Value-123'}
            with patch.object(security, 'ROOT', directory), patch.dict(os.environ, env):
                security.bootstrap()
                local, admin, catalog = security.material()
                original = {file: (local / file).read_bytes() for file in security.FILES}
                security.bootstrap()
                self.assertEqual(original, {file: (local / file).read_bytes() for file in security.FILES})
                self.assertEqual((local / 'node-key.pem').stat().st_mode & 0o777, 0o600)
                subprocess.run(['openssl', 'verify', '-CAfile', str(local / 'ca.pem'),
                    '-verify_hostname', 'opensearch.opensearch.svc.cluster.local', str(local / 'node.pem')],
                    check=True, capture_output=True)
                secrets, values = runtime.build('opensearch')
                users = json.loads(secrets[0]['stringData']['internal_users.yml'])
                self.assertEqual(set(users), {'_meta', admin, catalog})
                roles = json.loads(secrets[0]['stringData']['roles_mapping.yml'])
                self.assertNotIn('catalog_indexer', roles['bootstrap_admin']['backend_roles'])
                for password in env.values():
                    if password.startswith('Synthetic-'):
                        self.assertNotIn(password, json.dumps(secrets) + json.dumps(values))
                self.assertNotIn(base64.b64encode((local / 'ca-key.pem').read_bytes()).decode(), json.dumps(secrets))
                with patch.dict(os.environ, {'OPENMETADATA_SEARCH_PASSWORD': 'Different-Synthetic-Value-123'}), self.assertRaises(ValueError):
                    security.material()

                # Use ephemeral matching DER keys to exercise the catalog volume wiring.
                private = directory / 'private.der'
                public = directory / 'public.der'
                subprocess.run(['openssl', 'pkcs8', '-topk8', '-nocrypt', '-in', str(local / 'node-key.pem'),
                    '-outform', 'DER', '-out', str(private)], check=True, capture_output=True)
                subprocess.run(['openssl', 'pkey', '-inform', 'DER', '-in', str(private),
                    '-pubout', '-outform', 'DER', '-out', str(public)], check=True, capture_output=True)
                metadata_env = {
                    'OPENMETADATA_JWT_PRIVATE_KEY_FILE': str(private), 'OPENMETADATA_JWT_PUBLIC_KEY_FILE': str(public),
                    'OPENMETADATA_SEARCH_TRUSTSTORE_FILE': str(local / 'truststore.jks'),
                    'OPENMETADATA_FERNET_KEY': base64.urlsafe_b64encode(bytes(range(32))).decode(),
                    'OPENMETADATA_PUBLIC_URL': 'https://metadata.example',
                    'OPENMETADATA_DB_HOST': 'postgres.example', 'OPENMETADATA_DB_NAME': 'catalog',
                    'OPENMETADATA_DB_USER': 'catalog-owner', 'OPENMETADATA_DB_PASSWORD': 'Synthetic-DB-Value-123',
                    'OPENMETADATA_SEARCH_HOST': 'opensearch.opensearch.svc.cluster.local',
                    'OPENMETADATA_ADMIN_PRINCIPAL': 'owner', 'OPENMETADATA_PRINCIPAL_DOMAIN': 'example',
                    'OPENMETADATA_OIDC_CLIENT_ID': 'catalog', 'OPENMETADATA_OIDC_CLIENT_SECRET': 'Synthetic-OIDC-Value-123',
                    'OPENMETADATA_OIDC_AUTHORITY': 'https://identity.example',
                    'OPENMETADATA_OIDC_DISCOVERY_URL': 'https://identity.example/.well-known/openid-configuration',
                    'OPENMETADATA_OIDC_JWKS_URL': 'https://identity.example/keys'}
                with patch.dict(os.environ, metadata_env):
                    metadata_secrets, metadata_values = runtime.build('openmetadata')
                    trust = metadata_values['openmetadata']['config']['elasticsearch']['trustStore']
                    self.assertTrue(trust['enabled'])
                    self.assertEqual({v['name'] for v in metadata_values['extraVolumes']}, {'jwt-keys', 'search-ca'})
                    secret = next(s for s in metadata_secrets if s['metadata']['name'] == 'openmetadata-search-tls')
                    self.assertEqual(base64.b64decode(secret['data']['truststore.jks']), (local / 'truststore.jks').read_bytes())
                    self.assertNotIn(env['OPENSEARCH_TRUSTSTORE_PASSWORD'], json.dumps(metadata_values))
                chart_dir = os.environ.get('ALIAS_CHARTS_DIR')
                helm = os.environ.get('ALIAS_HELM')
                if chart_dir and helm:
                    for component, overlay in [('opensearch', values), ('openmetadata', metadata_values)]:
                        override = directory / (component + '.json')
                        override.write_text(json.dumps(overlay))
                        archive = Path(chart_dir) / (component + '.tgz')
                        if component == 'openmetadata':
                            prepared = directory / 'pinned.tgz'
                            subprocess.run([sys.executable, str(ROOT / 'scripts/prepare-openmetadata-chart.py'),
                                            str(archive), str(prepared)], check=True)
                            archive = prepared
                        result = subprocess.run([helm, 'template', component, str(archive), '--namespace', component,
                            '--kube-version', '1.34.13', '-f', str(ROOT / component / 'values.yaml'), '-f', str(override),
                            '-f', str(ROOT / 'versions' / (component + '.values.json')),
                            '--post-renderer', str(ROOT / 'scripts/locked-images.py')],
                            check=True, capture_output=True, text=True)
                        docs = list(yaml.safe_load_all(result.stdout))
                        for doc in docs:
                            if not doc or doc.get('kind') not in ('StatefulSet', 'Deployment'):
                                continue
                            pod = doc['spec']['template']['spec']
                            for container in pod.get('containers', []) + pod.get('initContainers', []):
                                self.assertRegex(container['image'], r'@sha256:[a-f0-9]{64}$')
                        if component == 'opensearch':
                            service = next(x for x in docs if x and x['kind'] == 'Service' and x['metadata']['name'] == 'opensearch')
                            self.assertEqual(service['spec']['type'], 'ClusterIP')
                            statefulset = next(x for x in docs if x and x['kind'] == 'StatefulSet')
                            self.assertTrue(statefulset['spec']['volumeClaimTemplates'])


if __name__ == '__main__':
    unittest.main()
