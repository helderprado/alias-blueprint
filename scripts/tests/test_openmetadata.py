"""Focused offline check of catalog Secrets and the real pinned chart."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class OpenMetadataTests(unittest.TestCase):
    def test_runtime_and_pinned_chart(self):
        with tempfile.TemporaryDirectory(prefix='alias-om-') as directory:
            d = Path(directory)
            local = d / 'openmetadata'
            local.mkdir()
            shutil.copyfile(ROOT / 'openmetadata/gen-keys.sh', local / 'gen-keys.sh')
            subprocess.run(['bash', str(local / 'gen-keys.sh')], check=True, capture_output=True)
            private = local / 'runtime-creds/private_key.der'
            original = private.read_bytes()
            subprocess.run(['bash', str(local / 'gen-keys.sh')], check=True, capture_output=True)
            self.assertEqual(private.read_bytes(), original)
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            env = {
                'OPENMETADATA_JWT_PRIVATE_KEY_FILE': str(private),
                'OPENMETADATA_JWT_PUBLIC_KEY_FILE': str(local / 'runtime-creds/public_key.der'),
                'OPENMETADATA_FERNET_KEY': base64.urlsafe_b64encode(bytes(range(32))).decode(),
                'OPENMETADATA_PUBLIC_URL': 'https://metadata.example',
                'OPENMETADATA_DB_HOST': 'postgres.example', 'OPENMETADATA_DB_NAME': 'catalog',
                'OPENMETADATA_DB_USER': 'catalog-owner', 'OPENMETADATA_DB_PASSWORD': 'synthetic-db-secret',
                'OPENMETADATA_SEARCH_HOST': 'search.example', 'OPENMETADATA_SEARCH_USER': 'catalog-indexer',
                'OPENMETADATA_SEARCH_PASSWORD': 'synthetic-search-secret',
                'OPENMETADATA_ADMIN_PRINCIPAL': 'owner', 'OPENMETADATA_PRINCIPAL_DOMAIN': 'example',
                'OPENMETADATA_OIDC_CLIENT_ID': 'catalog', 'OPENMETADATA_OIDC_CLIENT_SECRET': 'synthetic-oidc-secret',
                'OPENMETADATA_OIDC_AUTHORITY': 'https://identity.example',
                'OPENMETADATA_OIDC_DISCOVERY_URL': 'https://identity.example/.well-known/openid-configuration',
                'OPENMETADATA_OIDC_JWKS_URL': 'https://identity.example/keys',
            }
            real_run = subprocess.run
            calls = []
            def cluster_mock(args, **kwargs):
                if args[0] == 'openssl':
                    return real_run(args, **kwargs)
                self.assertEqual(args[0], 'kubectl')
                calls.append((args, kwargs))
                return SimpleNamespace(stdout='{"items": []}')
            output = d / 'values.json'
            with patch.dict(os.environ, env), patch.object(sys, 'argv', ['runtime', 'openmetadata', str(output)]), patch.object(runtime.subprocess, 'run', side_effect=cluster_mock):
                runtime.main()
                self.assertEqual(json.loads(calls[0][1]['input'])['kind'], 'Namespace')
                secrets = json.loads(calls[-1][1]['input'])['items']
                self.assertEqual(secrets[0]['data']['private_key.der'], base64.b64encode(original).decode())
                values = json.loads(output.read_text())
                self.assertEqual(values['openmetadata']['config']['database']['auth']['password']['secretRef'], 'openmetadata-runtime')
                for name in ['OPENMETADATA_DB_PASSWORD', 'OPENMETADATA_SEARCH_PASSWORD', 'OPENMETADATA_OIDC_CLIENT_SECRET', 'OPENMETADATA_FERNET_KEY']:
                    self.assertNotIn(env[name], output.read_text())
                calls.clear()
                with patch.dict(os.environ, {'OPENMETADATA_DB_PASSWORD': ''}), self.assertRaises(ValueError):
                    runtime.main()
                self.assertEqual(calls, [])
            chart_dir = os.environ.get('ALIAS_CHARTS_DIR')
            helm = os.environ.get('ALIAS_HELM')
            if chart_dir and helm:
                patched = d / 'pinned.tgz'
                real_run([sys.executable, str(ROOT / 'scripts/prepare-openmetadata-chart.py'),
                          str(Path(chart_dir) / 'openmetadata.tgz'), str(patched)], check=True)
                result = real_run([helm, 'template', 'openmetadata', str(patched),
                    '--namespace', 'openmetadata', '--kube-version', '1.34.13',
                    '-f', str(ROOT / 'openmetadata/values.yaml'), '-f', str(output),
                    '-f', str(ROOT / 'versions/openmetadata.values.json'),
                    '--post-renderer', str(ROOT / 'scripts/locked-images.py')], capture_output=True, text=True, check=True)
                def inspect(value):
                    if isinstance(value, dict):
                        if isinstance(value.get('image'), str):
                            self.assertRegex(value['image'], r'@sha256:[a-f0-9]{64}$')
                        for child in value.values():
                            inspect(child)
                    elif isinstance(value, list):
                        for child in value:
                            inspect(child)
                for doc in yaml.safe_load_all(result.stdout):
                    inspect(doc)


if __name__ == '__main__':
    unittest.main()
