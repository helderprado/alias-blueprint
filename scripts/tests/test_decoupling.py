"""Small independence checks; no cluster, network, image build or service install."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import opensearch_security as security
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class DecouplingTests(unittest.TestCase):
    def test_airflow_with_own_environment_only(self):
        env = {'AIRFLOW_FERNET_KEY': base64.urlsafe_b64encode(bytes(range(32))).decode(),
               'AIRFLOW_WEBSERVER_SECRET_KEY': 'synthetic-web-key',
               'AIRFLOW_DATABASE_URL': 'postgresql://user:synthetic-value@db.example/airflow'}
        with patch.dict(os.environ, env, clear=True):
            secrets, values = runtime.build('airflow')
            self.assertEqual(len(secrets), 3)
            self.assertFalse(values['dags']['gitSync']['enabled'])
            self.assertFalse(values['dags']['persistence']['enabled'])
            self.assertNotIn('openmetadata', json.dumps(values).lower())
            with patch.dict(os.environ, {'AIRFLOW_DAGS_GIT_REPO': 'https://git.example/my-dags.git'}), self.assertRaises(ValueError):
                runtime.build('airflow')
            with patch.dict(os.environ, {'AIRFLOW_DAGS_GIT_REPO': 'https://git.example/my-dags.git',
                                        'AIRFLOW_DAGS_GIT_REF': 'a' * 40}):
                _, values = runtime.build('airflow')
                self.assertTrue(values['dags']['gitSync']['enabled'])
                self.assertEqual(values['dags']['gitSync']['ref'], 'a' * 40)

    def test_search_admin_only_and_optional_account(self):
        env = {'OPENSEARCH_ADMIN_PASSWORD': 'Synthetic-Admin-Value-123',
               'OPENSEARCH_TRUSTSTORE_PASSWORD': 'Synthetic-Trust-Value-123'}
        with patch.dict(os.environ, env, clear=True):
            admin, app, passwords, scopes = security.inputs()
            self.assertIsNone(app)
            self.assertEqual(scopes, [])
            self.assertEqual(set(passwords), set(env))
            with tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                (directory / 'admin.hash').write_text('synthetic-hash')
                documents = security.security_documents(directory, admin, app)
                self.assertEqual(set(documents['internal_users.yml']), {'_meta', admin})
                self.assertEqual(set(documents['roles_mapping.yml']), {'_meta', 'bootstrap_admin'})
            with patch.dict(os.environ, {'OPENSEARCH_APP_USER': 'logs-client'}), self.assertRaises(ValueError):
                security.inputs()
            with patch.dict(os.environ, {'OPENSEARCH_APP_USER': 'logs-client',
                                        'OPENSEARCH_APP_PASSWORD': 'Synthetic-App-Value-123',
                                        'OPENSEARCH_APP_INDEX_PATTERNS': 'logs-*,events-*'}):
                _, app, _, scopes = security.inputs()
                self.assertEqual(app, 'logs-client')
                self.assertEqual(scopes, ['logs-*', 'events-*'])


if __name__ == '__main__':
    unittest.main()
