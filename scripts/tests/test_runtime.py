"""Offline integration checks: never call a cluster or a real Helm executable."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            'JUPYTERHUB_CRYPT_KEY': 'a' * 64, 'JUPYTERHUB_AUTH_PASSWORD': 'synthetic-hub-password',
            'MLFLOW_DB_HOST': 'mysql.example', 'MLFLOW_DB_NAME': 'tracking',
            'MLFLOW_DB_USER': 'tracking-user', 'MLFLOW_DB_PASSWORD': 'synthetic-db-password',
            'MLFLOW_S3_BUCKET': 'tracking', 'MLFLOW_S3_ENDPOINT_URL': 'https://objects.example',
            'MLFLOW_S3_ACCESS_KEY_ID': 'synthetic-access', 'MLFLOW_S3_SECRET_ACCESS_KEY': 'synthetic-object-key',
            'SUPERSET_SECRET_KEY': 'synthetic-superset-key', 'SUPERSET_DB_HOST': 'postgres.example',
            'SUPERSET_DB_NAME': 'analytics', 'SUPERSET_DB_USER': 'analytics-user',
            'SUPERSET_DB_PASSWORD': 'synthetic-analytics-password', 'SUPERSET_REDIS_PASSWORD': 'synthetic-cache-password',
            'AIRFLOW_FERNET_KEY': base64.urlsafe_b64encode(bytes(range(32))).decode(),
            'AIRFLOW_WEBSERVER_SECRET_KEY': 'synthetic-web-key',
            'AIRFLOW_DATABASE_URL': 'postgresql://user:synthetic-password@postgres.example/airflow',
            'REGISTRY_HOST': 'registry.example', 'REGISTRY_USER': 'image-reader',
            'REGISTRY_PASSWORD': 'synthetic-pull-password',
        }

    def test_secrets_are_referenced_without_values_in_overlay(self):
        sensitive = [v for k, v in self.env.items() if any(s in k for s in ['PASSWORD', 'SECRET', 'FERNET', 'CRYPT', 'DATABASE_URL'])]
        with patch.dict(os.environ, self.env, clear=True):
            for component in ['jupyterhub', 'mlflow', 'superset', 'airflow']:
                secrets, overlay = runtime.build(component)
                self.assertTrue(secrets)
                self.assertTrue(all(s['metadata']['namespace'] == component for s in secrets))
                for value in sensitive:
                    self.assertNotIn(value, json.dumps(overlay))
            secrets, values = runtime.build('mlflow')
            self.assertEqual(values['backendStore']['existingDatabaseSecret']['name'], secrets[0]['metadata']['name'])
            self.assertEqual(values['artifactRoot']['s3']['existingSecret']['name'], secrets[0]['metadata']['name'])
            secrets, values = runtime.build('airflow')
            self.assertFalse(values['postgresql']['enabled'])
            self.assertEqual(secrets[2]['stringData']['connection'], self.env['AIRFLOW_DATABASE_URL'])

    def test_each_required_variable_is_validated(self):
        groups = {
            'jupyterhub': ['JUPYTERHUB_CRYPT_KEY', 'JUPYTERHUB_AUTH_PASSWORD'],
            'mlflow': [k for k in self.env if k.startswith('MLFLOW_')],
            'superset': [k for k in self.env if k.startswith('SUPERSET_')],
            'airflow': [k for k in self.env if k.startswith('AIRFLOW_')],
        }
        for component, names in groups.items():
            for name in names:
                with self.subTest(component=component, missing=name):
                    env = self.env | {name: ''}
                    with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                        runtime.build(component)
        for name in ['JUPYTERHUB_CRYPT_KEY', 'AIRFLOW_FERNET_KEY']:
            with patch.dict(os.environ, self.env | {name: 'invalid'}, clear=True), self.assertRaises(ValueError):
                runtime.build('jupyterhub' if name.startswith('JUPYTER') else 'airflow')

    def test_deploy_entrypoints_load_env_and_clean_overrides(self):
        with tempfile.TemporaryDirectory(prefix='alias-runtime-tests-') as d:
            d = Path(d)
            stub = '''#!/usr/bin/env python3
import sys,os,json,pathlib
command=pathlib.Path(sys.argv[0]).name
record={'command':command,'args':sys.argv[1:]}
if command=='kubectl': record['payload']=json.loads(sys.stdin.read())
else:
 paths=[sys.argv[i+1] for i,a in enumerate(sys.argv[:-1]) if a=='--values']
 record['override_path']=paths[-1]
 record['values']=json.loads(pathlib.Path(paths[-1]).read_text())
with open(os.environ['TEST_LOG'],'a') as f: f.write(json.dumps(record)+'\\n')
'''
            for cmd in ['kubectl', 'helm']:
                p = d / cmd
                p.write_text(stub)
                p.chmod(0o700)
            config = d / 'test.env'
            config.write_text('\n'.join(k + "='" + v + "'" for k, v in self.env.items()))
            env = {k: v for k, v in os.environ.items() if not k.startswith(('MLFLOW_', 'AIRFLOW_', 'JUPYTERHUB_', 'SUPERSET_', 'REGISTRY_'))}
            env.update(ALIAS_ENV_FILE=str(config), PATH=str(d) + ':' + env['PATH'], TEST_LOG=str(d / 'calls'))
            for component in ['jupyterhub', 'mlflow', 'superset', 'airflow']:
                log = d / 'calls'
                log.write_text('')
                result = subprocess.run(['bash', str(ROOT / component / 'deploy.sh')], cwd=d,
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = [json.loads(l) for l in log.read_text().splitlines()]
                self.assertEqual([r['command'] for r in records], ['kubectl', 'helm'])
                self.assertFalse(Path(records[-1]['override_path']).exists())
                for k, value in self.env.items():
                    if any(s in k for s in ['PASSWORD', 'SECRET', 'FERNET', 'CRYPT', 'DATABASE_URL']):
                        self.assertNotIn(value, json.dumps(records[-1]) + result.stdout + result.stderr)
            config.write_text('MLFLOW_DB_PASSWORD=\n')
            log.write_text('')
            result = subprocess.run(['bash', str(ROOT / 'mlflow/deploy.sh')], env=env,
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log.read_text(), '')
            # Pull wrappers use the same file loader; no interactive input needed.
            config.write_text('\n'.join(k + "='" + v + "'" for k, v in self.env.items()))
            for wrapper in ['airflow/docker-secrets.sh', 'spark/docker-secret.sh', 'spark-operator/docker-secret.sh', 'jupyterhub/docker-secret.sh']:
                log.write_text('')
                result = subprocess.run(['bash', str(ROOT / wrapper)], cwd=d, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = [json.loads(l) for l in log.read_text().splitlines()]
                self.assertEqual(records[0]['payload']['items'][1]['kind'], 'ServiceAccount')


if __name__ == '__main__':
    unittest.main()
