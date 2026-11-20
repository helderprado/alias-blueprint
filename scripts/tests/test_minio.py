"""MinIO storage/credential isolation and offline Helm integration."""
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
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import minio_runtime as minio

spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
HELM = os.environ.get('ALIAS_HELM') or shutil.which('helm')


class MinioTests(unittest.TestCase):
    def setUp(self):
        self.env = {'MINIO_IMAGE': 'registry.example/alias-minio@sha256:' + 'a' * 64,
                    'MINIO_ROOT_USER': 'synthetic-root-user', 'MINIO_ROOT_PASSWORD': 'synthetic-root-password',
                    'MINIO_STORAGE_CLASS': 'local-path', 'MINIO_CLIENTS': 'mlflow,spark',
                    'MINIO_MLFLOW_ACCESS_KEY': 'synthetic-mlflow-access', 'MINIO_MLFLOW_SECRET_KEY': 'synthetic-mlflow-secret',
                    'MINIO_SPARK_ACCESS_KEY': 'synthetic-spark-access', 'MINIO_SPARK_SECRET_KEY': 'synthetic-spark-secret',
                    'MINIO_MLFLOW_BUCKETS': 'mlflow', 'MINIO_SPARK_BUCKETS': 'datasets',
                    'MINIO_ALLOWED_NAMESPACES': 'mlflow,spark-operator'}

    def test_scoped_policies_and_no_credentials_in_values(self):
        with patch.dict(os.environ, self.env, clear=True):
            secrets, values = runtime.build('minio')
        self.assertEqual(len(secrets), 3)
        for key, value in self.env.items():
            if key.endswith(('PASSWORD', 'ACCESS_KEY', 'SECRET_KEY', 'ROOT_USER')):
                self.assertNotIn(value, json.dumps(values))
        for client in values['clients']:
            statements = client['policy']['Statement']
            self.assertTrue(all(a.startswith('s3:') for s in statements for a in s['Action']))
            self.assertEqual(statements[0]['Resource'], ['arn:aws:s3:::' + client['buckets'][0]])
            self.assertEqual(statements[1]['Resource'], ['arn:aws:s3:::' + client['buckets'][0] + '/*'])

    def test_invalid_inputs_fail_before_cluster_requests(self):
        cases = [{'MINIO_IMAGE': 'minio/minio:unreviewed'}, {'MINIO_STORAGE_CLASS': ''},
                 {'MINIO_EXISTING_CLAIM': 'shared'}, {'MINIO_CPU_REQUEST': '2', 'MINIO_CPU_LIMIT': '1'},
                 {'MINIO_MEMORY_REQUEST': '2Gi', 'MINIO_MEMORY_LIMIT': '1Gi'},
                 {'MINIO_ROOT_PASSWORD': ''}, {'MINIO_CLIENTS': 'bad;command'},
                 {'MINIO_SPARK_ACCESS_KEY': self.env['MINIO_MLFLOW_ACCESS_KEY']},
                 {'MINIO_MLFLOW_BUCKETS': '*'}, {'MINIO_ALLOWED_NAMESPACES': 'default,;oops'}]
        with patch.object(subprocess, 'run') as run:
            for changes in cases:
                with self.subTest(changes=changes), patch.dict(os.environ, self.env | changes, clear=True):
                    with self.assertRaises(ValueError):
                        runtime.build('minio')
            run.assert_not_called()

    def test_dedicated_existing_claim_and_storage_migration_checks(self):
        env = self.env | {'MINIO_STORAGE_CLASS': '', 'MINIO_EXISTING_CLAIM': 'object-data'}
        with patch.dict(os.environ, env, clear=True):
            _, values = minio.build()
        deployment = {'spec': {'template': {'spec': {'volumes': [
            {'name': 'data', 'persistentVolumeClaim': {'claimName': 'old-data'}}]}}}}
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(deployment))):
            with self.assertRaisesRegex(ValueError, 'migration'):
                minio.preflight(values)
        for phase in ('Pending', 'Bound'):
            responses = [subprocess.CompletedProcess([], 0, ''), subprocess.CompletedProcess([], 0, json.dumps(
                {'status': {'phase': phase}, 'spec': {'volumeMode': 'Filesystem'}}))]
            if phase == 'Bound':
                responses.append(subprocess.CompletedProcess([], 0, '{"items": []}'))
            with patch.object(subprocess, 'run', side_effect=responses):
                if phase == 'Pending':
                    with self.assertRaisesRegex(ValueError, 'Bound'):
                        minio.preflight(values)
                else:
                    minio.preflight(values)
        responses = [subprocess.CompletedProcess([], 0, ''),
                     subprocess.CompletedProcess([], 0, '{"status":{"phase":"Bound"}}'),
                     subprocess.CompletedProcess([], 0, json.dumps({'items': [
                         {'spec': {'volumes': [{'persistentVolumeClaim': {'claimName': 'object-data'}}]}}]}))]
        with patch.object(subprocess, 'run', side_effect=responses):
            with self.assertRaisesRegex(ValueError, 'another workload'):
                minio.preflight(values)

    def test_deploy_uses_atomic_helm_and_removes_credential_free_temporary_values(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            stub = '''#!/usr/bin/env python3
import json, os, pathlib, sys
command = pathlib.Path(sys.argv[0]).name
record = {'command': command, 'args': sys.argv[1:]}
if command == 'kubectl':
    if sys.argv[1:3] == ['get', 'secret']:
        print('{"items": []}')
    elif sys.argv[1] == 'apply':
        record['kind'] = json.loads(sys.stdin.read())['kind']
else:
    path = sys.argv[sys.argv.index('--values') + 1]
    record['valuesPath'] = path
    record['values'] = json.loads(pathlib.Path(path).read_text())
with open(os.environ['TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(record) + '\\n')
'''
            for command in ('helm', 'kubectl'):
                path = directory / command
                path.write_text(stub)
                path.chmod(0o700)
            config = directory / 'minio.env'
            config.write_text('')
            log = directory / 'calls'
            env = os.environ | self.env | {'PATH': str(directory) + ':' + os.environ['PATH'],
                                           'ALIAS_ENV_FILE': str(config), 'TEST_LOG': str(log)}
            result = subprocess.run(['bash', str(ROOT / 'minio/deploy.sh')], env=env,
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            helm = calls[-1]
            self.assertEqual(helm['command'], 'helm')
            self.assertIn('--atomic', helm['args'])
            self.assertIn(str(ROOT / 'minio/chart'), helm['args'])
            self.assertFalse(Path(helm['valuesPath']).exists())
            self.assertEqual([c.get('kind') for c in calls if c['args'][0] == 'apply'], ['Namespace', 'List'])
            for key in ('MINIO_ROOT_PASSWORD', 'MINIO_MLFLOW_SECRET_KEY', 'MINIO_SPARK_SECRET_KEY'):
                self.assertNotIn(self.env[key], log.read_text() + result.stdout + result.stderr)

    def test_changed_runtime_secret_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, self.env, clear=True):
            secrets, _ = minio.build()
            old = {'kind': 'Secret', 'metadata': {'name': 'minio-root'},
                   'data': {k: base64.b64encode(v.encode()).decode() for k, v in secrets[0]['stringData'].items()}}
            old['data']['rootPassword'] = base64.b64encode(b'changed-live-password').decode()
            responses = [subprocess.CompletedProcess([], 0, ''), subprocess.CompletedProcess([], 0, json.dumps({'items': [old]}))]
            with patch.object(sys, 'argv', ['runtime-secrets.py', 'minio', directory + '/values']), \
                    patch.object(subprocess, 'run', side_effect=responses) as run:
                with self.assertRaisesRegex(ValueError, 'Credential changes'):
                    runtime.main()
                self.assertEqual(run.call_count, 2)  # Namespace apply and Secret read only.

    def test_private_connection_exports_only_selected_account(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, self.env, clear=True):
            path = Path(directory) / 'connection.env'
            minio.write_connection('mlflow', path)
            text = path.read_text()
            self.assertIn('MLFLOW_S3_ENDPOINT_URL=http://minio.minio.svc.cluster.local:9000', text)
            self.assertIn(self.env['MINIO_MLFLOW_SECRET_KEY'], text)
            self.assertNotIn(self.env['MINIO_SPARK_SECRET_KEY'], text)
            self.assertNotIn(self.env['MINIO_ROOT_PASSWORD'], text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                minio.write_connection('mlflow', path)

    def test_interactive_configuration_generates_private_file_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'minio.env'
            answers = '\n'.join([self.env['MINIO_IMAGE']] + [''] * 12) + '\n'
            result = subprocess.run([sys.executable, str(ROOT / 'minio/configure.py'), '--output', str(output)],
                                    input=answers, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            text = output.read_text()
            secret_line = next(l for l in text.splitlines() if l.startswith('MINIO_ROOT_PASSWORD='))
            self.assertNotIn(secret_line.split('=', 1)[1], result.stdout + result.stderr)
            original = output.read_bytes()
            result = subprocess.run([sys.executable, str(ROOT / 'minio/configure.py'), '--output', str(output)],
                                    input='', text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    @unittest.skipUnless(HELM, 'Set ALIAS_HELM for offline chart rendering')
    def test_render_entrypoint_dynamic_and_existing_pvc_tls_no_cluster_or_secret_leaks(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                (directory / 'helm').symlink_to(HELM)
                (directory / 'kubectl').write_text('#!/bin/sh\necho unexpected-cluster-call >&2\nexit 99\n')
                (directory / 'kubectl').chmod(0o700)
                config = directory / 'minio.env'
                config.write_text('')
                env = os.environ | self.env | {'ALIAS_ENV_FILE': str(config), 'PATH': str(directory) + ':' + os.environ['PATH']}
                if existing:
                    env.update(MINIO_STORAGE_CLASS='', MINIO_EXISTING_CLAIM='dedicated-data', MINIO_TLS_SECRET='minio-tls')
                result = subprocess.run(['bash', str(ROOT / 'minio/deploy.sh'), '--render'], env=env,
                                        cwd=directory, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                documents = list(yaml.safe_load_all(result.stdout))
                self.assertFalse(any(d['kind'] == 'Secret' for d in documents))
                pvcs = [d for d in documents if d['kind'] == 'PersistentVolumeClaim']
                self.assertEqual(len(pvcs), 0 if existing else 1)
                if pvcs:
                    self.assertEqual(pvcs[0]['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
                deployment = next(d for d in documents if d['kind'] == 'Deployment')
                pod = deployment['spec']['template']['spec']
                self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
                self.assertEqual(pod['containers'][0]['readinessProbe']['httpGet']['scheme'], 'HTTPS' if existing else 'HTTP')
                self.assertEqual(pod['containers'][0]['image'], self.env['MINIO_IMAGE'])
                claim = next(v for v in pod['volumes'] if v['name'] == 'data')['persistentVolumeClaim']['claimName']
                self.assertEqual(claim, 'dedicated-data' if existing else 'minio-data')
                job = next(d for d in documents if d['kind'] == 'Job')
                self.assertEqual(job['spec']['template']['spec']['containers'][0]['image'], self.env['MINIO_IMAGE'])
                service = next(d for d in documents if d['kind'] == 'Service')
                self.assertEqual(service['spec']['type'], 'ClusterIP')
                policy = next(d for d in documents if d['kind'] == 'NetworkPolicy')
                self.assertTrue(all(rule['ports'] == [{'protocol': 'TCP', 'port': 9000}]
                                    for rule in policy['spec']['ingress'][1:]))
                for key in ('MINIO_ROOT_PASSWORD', 'MINIO_MLFLOW_SECRET_KEY', 'MINIO_SPARK_SECRET_KEY'):
                    self.assertNotIn(self.env[key], result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
