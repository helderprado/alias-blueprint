"""Optional real-chart rendering of every local profile, without a running cluster."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_smoke_charts', ROOT / 'scripts/local-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class RenderLab(smoke.Lab):
    def __init__(self, path):
        super().__init__(argparse.Namespace(mode='run', components='all', timeout=60, build_timeout=60, keep=False))
        self.path = path
        self.project = path / 'project'
        self.bin = path / 'bin'
        self.env['ALIAS_ENV_FILE'] = str(path / 'test.env')
        self.helm = os.environ['ALIAS_HELM']
        self.registry_port = '30500'
        self.rendered = {}
        self.snapshot()
        self.spark_template = json.loads(self.command(['bash', str(self.project / 'spark/submit.sh'), '--render']))

    def namespace(self, name):
        pass

    def apply(self, *documents):
        pass

    def configmap(self, *args):
        pass

    def workload(self, *args, **kwargs):
        pass

    def probe(self, *args, **kwargs):
        pass

    def k(self, *args, **kwargs):
        if 'secret' in args:
            import base64
            return json.dumps({'data': {'tls.crt': base64.b64encode(b'synthetic-public-ca').decode()}})
        return '{}'

    def command(self, args, **kwargs):
        return super().command(args, **kwargs)

    def root_command(self, args, **kwargs):
        return '262144' if 'sysctl' in args else ''

    def build_image(self, name, directory):
        return 'local-registry:5000/' + name + '@sha256:' + '1' * 64

    def image_digest(self, *args):
        return self.build_image('probe', '')

    def chart(self, name):
        chart = self.lock['charts'][name]
        archive = Path(os.environ['ALIAS_SMOKE_CHARTS_DIR']) / (name + '-' + chart['version'] + '.tgz')
        import hashlib
        if hashlib.sha256(archive.read_bytes()).hexdigest() != chart['digest']:
            raise ValueError('Bad fixture chart checksum: ' + name)
        if name in ('trino', 'openmetadata'):
            patched = self.path / (name + '-patched.tgz')
            self.command([self.py, str(self.project / 'scripts' / ('prepare-' + name + '-chart.py')), str(archive), str(patched)])
            return patched
        return archive

    def deploy(self, name, overrides=None, runtime=True, namespace=None, release=None):
        archive = self.project / 'minio/chart' if name == 'minio' else self.chart(name)
        args = [self.helm, 'template', release or name, str(archive), '--namespace', namespace or name,
                '--kube-version', '1.34.13', '--post-renderer', str(self.project / 'scripts/locked-images.py')]
        baseline = self.project / name / 'values.yaml'
        if baseline.exists():
            args += ['-f', str(baseline)]
        if runtime:
            script = ('import sys,importlib.util,json; sys.path.insert(0,sys.argv[1]); '
                's=importlib.util.spec_from_file_location("runtime",sys.argv[1]+"/runtime-secrets.py"); '
                'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.build(sys.argv[2])[1]))')
            values = self.command([self.py, '-c', script, str(self.project / 'scripts'), name])
            target = self.path / (name + '.runtime.json')
            smoke.private(target, values)
            args += ['-f', str(target)]
        if overrides:
            target = self.path / (name + '.local.json')
            smoke.private(target, json.dumps(overrides))
            args += ['-f', str(target)]
        pinned = self.project / 'versions' / (name + '.values.json')
        if pinned.exists():
            args += ['-f', str(pinned)]
        self.rendered[name] = list(yaml.safe_load_all(self.command(args)))


@unittest.skipUnless(os.environ.get('ALIAS_HELM') and os.environ.get('ALIAS_SMOKE_CHARTS_DIR'),
                     'Set ALIAS_HELM and ALIAS_SMOKE_CHARTS_DIR for local-profile chart validation')
class LocalProfileChartTests(unittest.TestCase):
    def test_profiles_render_with_locked_images_and_valid_services(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = RenderLab(Path(directory))
            for name in ('registry', 'minio', 'mlflow', 'airflow', 'jupyterhub', 'opensearch',
                         'openmetadata', 'pinot', 'trino', 'superset', 'homepage', 'rancher'):
                with self.subTest(component=name):
                    getattr(lab, name)()
            lab.deploy('spark-operator', runtime=False)
            lab.deploy('cert-manager', {'installCRDs': True}, runtime=False)
            self.assertFalse(any(doc and doc.get('metadata', {}).get('name') == 'pinot-minion-stateless'
                                 for doc in lab.rendered['pinot']))
            redis = next(doc for doc in lab.rendered['superset'] if doc and doc['kind'] == 'StatefulSet'
                         and doc['metadata']['name'] == 'superset-redis-master')
            password = next(item for item in redis['spec']['template']['spec']['containers'][0]['env']
                            if item['name'] == 'REDIS_PASSWORD')
            self.assertEqual(password['valueFrom']['secretKeyRef'],
                             {'name': 'superset-runtime', 'key': 'REDIS_PASSWORD'})
            worker = next(doc for doc in lab.rendered['superset'] if doc and doc['kind'] == 'Deployment'
                          and doc['metadata']['name'] == 'superset-worker')
            self.assertEqual(worker['spec']['replicas'], 0)
            env_secret = next(doc for doc in lab.rendered['superset'] if doc and doc['kind'] == 'Secret'
                              and doc['metadata']['name'] == 'superset-env')
            self.assertEqual(env_secret['stringData']['DB_HOST'],
                             lab.values['SUPERSET_DB_HOST'])
            web = next(doc for doc in lab.rendered['superset'] if doc and doc['kind'] == 'Deployment'
                       and doc['metadata']['name'] == 'superset')
            mounts = web['spec']['template']['spec']['containers'][0]['volumeMounts']
            extra_path = next(mount['mountPath'] for mount in mounts if mount['name'] == 'superset-extra-config')
            config = next(doc for doc in lab.rendered['superset'] if doc and doc['kind'] == 'Secret'
                          and doc['metadata']['name'] == 'superset-config')
            bootstrap = config['stringData']['superset_bootstrap.sh']
            self.assertIn('-r ' + extra_path + '/requirements.lock', bootstrap)
            self.assertIn('set -eu', bootstrap)
            for name, docs in lab.rendered.items():
                for document in filter(None, docs):
                    if document['kind'] == 'Service':
                        service = document['spec']
                        if service.get('type') == 'NodePort':
                            self.assertEqual(name, 'registry')
                            self.assertTrue(all(30000 <= port.get('nodePort', 30000) <= 32767 for port in service['ports']))
                    def inspect(value):
                        if isinstance(value, dict):
                            if isinstance(value.get('image'), str):
                                self.assertRegex(value['image'], r'@sha256:[a-f0-9]{64}$')
                            for child in value.values():
                                inspect(child)
                        elif isinstance(value, list):
                            for child in value:
                                inspect(child)
                    inspect(document)


if __name__ == '__main__':
    unittest.main()
