"""Offline Spark resource, credential and real-chart integration checks."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import spark_runtime as spark


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = module('spark_test_runtime', ROOT / 'scripts/runtime-secrets.py')
fetch = module('spark_test_fetch', ROOT / 'docker-images/pyspark-aws-psql/fetch-jars.py')
storage = module('spark_test_storage', ROOT / 'glusterfs/storage.py')


class SparkTests(unittest.TestCase):
    def setUp(self):
        self.env = {'SPARK_IMAGE': 'registry.example/spark@sha256:' + 'a' * 64,
                    'SPARK_S3_ENABLED': 'true', 'SPARK_S3_ENDPOINT_URL': 'http://minio.minio.svc.cluster.local:9000',
                    'SPARK_S3_BUCKET': 'spark-data', 'SPARK_S3_ACCESS_KEY_ID': 'synthetic-spark-access',
                    'SPARK_S3_SECRET_ACCESS_KEY': 'synthetic-spark-secret', 'SPARK_DB_ENABLED': 'true',
                    'SPARK_DB_URL': 'jdbc:postgresql://db.example/analytics', 'SPARK_DB_USER': 'spark-reader',
                    'SPARK_DB_PASSWORD': 'synthetic-database-password'}

    def test_compute_only_and_optional_secrets_never_leak_into_application(self):
        with patch.dict(os.environ, {}, clear=True):
            app = spark.application()
            secrets, _ = runtime.build('spark')
            self.assertEqual(secrets, [])
            self.assertNotIn('hadoopConf', app['spec'])
            self.assertNotIn('envSecretKeyRefs', app['spec']['driver'])
        with patch.dict(os.environ, self.env, clear=True):
            app = spark.application()
            secrets, overlay = runtime.build('spark')
            rendered = json.dumps(app) + json.dumps(spark.resources()) + json.dumps(overlay)
        self.assertEqual(secrets[0]['metadata']['namespace'], 'spark')
        for key in ('SPARK_S3_ACCESS_KEY_ID', 'SPARK_S3_SECRET_ACCESS_KEY', 'SPARK_DB_PASSWORD', 'SPARK_DB_URL'):
            self.assertNotIn(self.env[key], rendered)
        for role in ('driver', 'executor'):
            refs = app['spec'][role]['envSecretKeyRefs']
            self.assertEqual(refs['AWS_SECRET_ACCESS_KEY'], {'name': 'spark-runtime', 'key': 'AWS_SECRET_ACCESS_KEY'})
            self.assertEqual(refs['DATABASE_PASSWORD']['name'], 'spark-runtime')
        self.assertEqual(app['spec']['hadoopConf']['fs.s3a.aws.credentials.provider'],
                         'com.amazonaws.auth.EnvironmentVariableCredentialsProvider')
        self.assertIn('s3a://spark-data/', app['spec']['arguments'][1])

    def test_invalid_profiles_fail_before_external_commands(self):
        cases = [{'SPARK_S3_SECRET_ACCESS_KEY': ''}, {'SPARK_DB_PASSWORD': ''},
                 {'SPARK_IMAGE': 'spark:unreviewed'}, {'SPARK_IMAGE': ''},
                 {'SPARK_EXECUTORS': '100'}, {'SPARK_DRIVER_MEMORY': '0g'},
                 {'SPARK_EXECUTOR_CPU_REQUEST': '2', 'SPARK_EXECUTOR_CPU_LIMIT': '1'},
                 {'SPARK_EXECUTORS': '4', 'SPARK_QUOTA_CPU': '2'}, {'SPARK_QUOTA_MEMORY': '1Gi'},
                 {'SPARK_S3_ENDPOINT_URL': 'https://user:password@objects.example'},
                 {'SPARK_S3_ENDPOINT_URL': 'https://objects.example/private'},
                 {'SPARK_S3_BUCKET': 'bad;command'}, {'SPARK_DAGS_PVC': '../other'},
                 {'SPARK_APPLICATION_NAME': 'bad;command'}, {'SPARK_S3_ENABLED': 'yes'}]
        with patch.object(subprocess, 'run') as run:
            for case in cases:
                with self.subTest(case=case), patch.dict(os.environ, self.env | case, clear=True):
                    with self.assertRaises(ValueError):
                        runtime.build('spark')
            run.assert_not_called()

    def test_namespace_permissions_aggregate_budget_and_gluster_claim(self):
        with patch.dict(os.environ, {'SPARK_DAGS_PVC': 'airflow-share-dag-pvc'}, clear=True):
            docs = spark.resources()['items']
            app = spark.application()
        self.assertTrue(all(d['kind'] != 'ClusterRoleBinding' for d in docs))
        roles = [d for d in docs if d['kind'] == 'Role']
        self.assertEqual(len(roles), 1)
        for rule in roles[0]['rules']:
            self.assertNotIn('*', rule['verbs'])
            self.assertNotIn('secrets', rule['resources'])
            if 'persistentvolumeclaims' in rule['resources']:
                self.assertEqual(rule['verbs'], ['get', 'list', 'watch'])
        quota = next(d for d in docs if d['kind'] == 'ResourceQuota')['spec']['hard']
        self.assertEqual(quota['limits.cpu'], '4')
        self.assertEqual(quota['limits.memory'], '8Gi')
        self.assertIn('limits.ephemeral-storage', quota)
        self.assertFalse(app['spec']['dynamicAllocation']['enabled'])
        volume = next(v for v in app['spec']['volumes'] if v['name'] == 'shared-files')
        self.assertTrue(volume['persistentVolumeClaim']['readOnly'])
        for role in ('driver', 'executor'):
            self.assertTrue(next(v for v in app['spec'][role]['volumeMounts'] if v['name'] == 'shared-files')['readOnly'])
            self.assertIn('memoryOverhead', app['spec'][role])
        with patch.dict(os.environ, {'GLUSTERFS_NFS_SERVER': 'gateway.example', 'GLUSTERFS_PROFILES': 'spark'}, clear=True):
            shared = storage.manifests()
        claim = next(d for d in shared if d['kind'] == 'PersistentVolumeClaim')
        self.assertEqual(claim['metadata']['namespace'], 'spark')
        self.assertEqual(claim['metadata']['name'], volume['persistentVolumeClaim']['claimName'])
        pv = next(d for d in shared if d['kind'] == 'PersistentVolume')
        self.assertEqual(pv['spec']['nfs']['path'], '/alias-data/dags')

    def test_generic_minio_connection_exports_work_without_consumer_coupling(self):
        env = {key: value for key, value in self.env.items() if not key.startswith('SPARK_S3_')}
        env.update(SPARK_S3_ENABLED='true', S3_ENDPOINT_URL='https://objects.example', S3_BUCKET='datasets',
                   AWS_ACCESS_KEY_ID='synthetic-generic-access', AWS_SECRET_ACCESS_KEY='synthetic-generic-secret')
        with patch.dict(os.environ, env, clear=True):
            app = spark.application()
            secret = spark.build()[0][0]
        self.assertEqual(app['spec']['hadoopConf']['fs.s3a.connection.ssl.enabled'], 'true')
        self.assertEqual(secret['stringData']['AWS_ACCESS_KEY_ID'], env['AWS_ACCESS_KEY_ID'])

    def test_legacy_global_permission_is_rejected_before_writes(self):
        old = {'roleRef': {'name': 'edit'}, 'subjects': [
            {'kind': 'ServiceAccount', 'name': 'spark', 'namespace': 'spark-operator'}]}
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'argv', ['spark_runtime.py', 'setup']), \
                patch.object(spark, 'run', return_value=json.dumps(old)) as run:
            with self.assertRaisesRegex(ValueError, 'cluster-wide edit'):
                spark.main()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:3], ['kubectl', 'get', 'clusterrolebinding'])

    def test_existing_job_and_unbound_pvc_are_not_modified(self):
        with patch.dict(os.environ, {}, clear=True):
            app = spark.application()
        with patch.object(spark, 'run', return_value=json.dumps(app)) as run:
            with self.assertRaisesRegex(ValueError, 'already exists'):
                spark.preflight_application(app)
            self.assertEqual(run.call_count, 1)
        with patch.dict(os.environ, {'SPARK_DAGS_PVC': 'pending-data'}, clear=True), \
                patch.object(spark, 'run', return_value='{"status":{"phase":"Pending"}}') as run:
            with self.assertRaisesRegex(ValueError, 'Bound'):
                spark.preflight_application(app)
            self.assertEqual(run.call_count, 1)

    def test_existing_secret_changes_are_refused(self):
        with patch.dict(os.environ, self.env, clear=True), tempfile.TemporaryDirectory() as directory:
            secret = spark.build()[0][0]
            secret['data'] = {k: base64.b64encode(v.encode()).decode() for k, v in secret.pop('stringData').items()}
            secret['data']['DATABASE_PASSWORD'] = base64.b64encode(b'changed-password').decode()
            responses = [subprocess.CompletedProcess([], 0, ''),
                         subprocess.CompletedProcess([], 0, json.dumps({'items': [secret]}))]
            with patch.object(sys, 'argv', ['runtime-secrets.py', 'spark', directory + '/values']), \
                    patch.object(subprocess, 'run', side_effect=responses) as run:
                with self.assertRaisesRegex(ValueError, 'Credential changes'):
                    runtime.main()
                self.assertEqual(run.call_count, 2)

    def test_setup_and_submit_entrypoints_with_no_live_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            stub = '''#!/usr/bin/env python3
import json, os, pathlib, sys
record={'args':sys.argv[1:]}
if sys.argv[1] in ('apply', 'create'):
 record['payload']=json.loads(sys.stdin.read())
elif sys.argv[2]=='secret':
 print('{"items":[]}')
with open(os.environ['TEST_LOG'],'a') as stream: stream.write(json.dumps(record)+'\\n')
'''
            tool = directory / 'kubectl'
            tool.write_text(stub)
            tool.chmod(0o700)
            config = directory / 'spark.env'
            config.write_text('\n'.join(k + "='" + v + "'" for k, v in self.env.items()))
            log = directory / 'calls'
            env = os.environ | {'PATH': str(directory) + ':' + os.environ['PATH'],
                                 'ALIAS_ENV_FILE': str(config), 'TEST_LOG': str(log)}
            for script in ('spark/setup.sh', 'spark/submit.sh', 'spark-operator/add-roles.sh'):
                log.write_text('')
                render = subprocess.run(['bash', str(ROOT / script), '--render'], cwd=directory, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(render.returncode, 0, render.stderr)
                self.assertEqual(log.read_text(), '')
                for key in ('SPARK_S3_SECRET_ACCESS_KEY', 'SPARK_DB_PASSWORD'):
                    self.assertNotIn(self.env[key], render.stdout + render.stderr)
                result = subprocess.run(['bash', str(ROOT / script)], cwd=directory, env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = [json.loads(line) for line in log.read_text().splitlines()]
                if script.endswith('submit.sh'):
                    self.assertEqual(records[-1]['args'][0], 'create')
                    self.assertEqual(records[-1]['payload']['kind'], 'SparkApplication')
                else:
                    self.assertEqual(records[-1]['payload']['kind'], 'List')
                    self.assertTrue(any(r.get('payload', {}).get('items', [{}])[0].get('kind') == 'Secret'
                                        for r in records if r['args'][0] == 'apply' and r.get('payload', {}).get('kind') == 'List'))
                for key in ('SPARK_S3_SECRET_ACCESS_KEY', 'SPARK_DB_PASSWORD'):
                    self.assertNotIn(self.env[key], result.stdout + result.stderr)

    def test_corrupt_jar_download_cannot_enter_the_spark_classpath(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for library in ('hadoop-client-api', 'hadoop-client-runtime'):
                (directory / (library + '-3.3.4.jar')).write_bytes(b'base fixture')
            path = directory / 'lock.json'
            valid = b'valid jar fixture'
            lock = {'hadoop_runtime': '3.3.4', 'artifacts': [{'file': 'test.jar', 'url': 'https://repo.example/test.jar',
                    'sha256': hashlib.sha256(valid).hexdigest()}]}
            path.write_text(json.dumps(lock))
            with patch.object(fetch, 'urlopen', return_value=io.BytesIO(b'corrupted bytes')):
                with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                    fetch.install(path, directory)
                self.assertFalse((directory / 'test.jar').exists())
            with patch.object(fetch, 'urlopen', return_value=io.BytesIO(valid)):
                fetch.install(path, directory)
            self.assertEqual((directory / 'test.jar').read_bytes(), valid)
            (directory / 'test.jar').write_bytes(b'existing unrelated bytes')
            with patch.object(fetch, 'urlopen') as download, self.assertRaisesRegex(ValueError, 'Existing JAR'):
                fetch.install(path, directory)
            download.assert_not_called()
            self.assertEqual((directory / 'test.jar').read_bytes(), b'existing unrelated bytes')

    @unittest.skipUnless(os.environ.get('ALIAS_HELM') and os.environ.get('ALIAS_SPARK_OPERATOR_CHART'),
                         'Set ALIAS_HELM and ALIAS_SPARK_OPERATOR_CHART for the pinned chart')
    def test_exact_chart_hooks_watch_namespace_and_crd_fields(self):
        archive = Path(os.environ['ALIAS_SPARK_OPERATOR_CHART'])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'helm').symlink_to(os.environ['ALIAS_HELM'])
            (directory / 'kubectl').write_text('#!/bin/sh\nexit 99\n')
            (directory / 'kubectl').chmod(0o700)
            config = directory / 'spark.env'
            config.write_text('')
            env = os.environ | {'ALIAS_ENV_FILE': str(config), 'SPARK_OPERATOR_CHART': str(archive),
                                 'PATH': str(directory) + ':' + os.environ['PATH']}
            result = subprocess.run(['bash', str(ROOT / 'spark-operator/deploy.sh'), '--render'], env=env,
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            docs = [d for d in yaml.safe_load_all(result.stdout) if d]
            deployment = next(d for d in docs if d['kind'] == 'Deployment')
            controller = deployment['spec']['template']['spec']['containers'][0]
            self.assertIn('-namespace=spark', controller['args'])
            self.assertIn('-enable-webhook=true', controller['args'])
            self.assertIn('resources', controller)
            self.assertFalse(any(d['kind'] == 'Role' and d['metadata']['name'] == 'spark-role' for d in docs))
            for doc in docs:
                if doc['kind'] in ('Deployment', 'Job'):
                    for container in doc['spec']['template']['spec']['containers']:
                        self.assertRegex(container['image'], r'@sha256:[a-f0-9]{64}$')
            with tarfile.open(archive) as source:
                crds = [yaml.safe_load(source.extractfile(n)) for n in source.getnames() if '/crds/' in n and n.endswith('.yaml')]
            crd = next(c for c in crds if c['spec']['names']['plural'] == 'sparkapplications')
            schema = next(v for v in crd['spec']['versions'] if v['name'] == 'v1beta2')['schema']['openAPIV3Schema']
            with patch.dict(os.environ, self.env | {'SPARK_DAGS_PVC': 'shared-dags'}, clear=True):
                app = spark.application()
            # Reject unknown CRD fields without requiring a live API server.
            def inspect(value, definition):
                if isinstance(value, dict):
                    properties = definition.get('properties', {})
                    additional = definition.get('additionalProperties')
                    for key, child in value.items():
                        self.assertTrue(key in properties or isinstance(additional, dict) or definition.get('x-kubernetes-preserve-unknown-fields'), key)
                        inspect(child, properties.get(key, additional or {}))
                elif isinstance(value, list):
                    for child in value:
                        inspect(child, definition.get('items', {}))
            inspect(app['spec'], schema['properties']['spec'])


if __name__ == '__main__':
    unittest.main()
