"""Version lock invariants and optional offline rendering of verified chart archives."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('locked_images', ROOT / 'scripts/locked-images.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class VersionTests(unittest.TestCase):
    def test_mysql_manifest_initializes_locked_84_on_separate_storage(self):
        documents = list(yaml.safe_load_all((ROOT / 'databases/mlflow-db/deploy.yaml').read_text()))
        resources = {doc['kind']: doc for doc in documents if doc}
        lock = json.loads((ROOT / 'versions.lock.json').read_text())
        deployment = resources['Deployment']
        pod = deployment['spec']['template']
        container = pod['spec']['containers'][0]
        self.assertEqual(container['image'], lock['images']['mysql:8.4.7'])
        self.assertFalse(any('5.7' in image for image in lock['images'] if 'mysql' in image))
        expected = {'MYSQL_ROOT_PASSWORD', 'MYSQL_DATABASE', 'MYSQL_USER', 'MYSQL_PASSWORD'}
        variables = {item['name']: item['valueFrom']['secretKeyRef'] for item in container['env']}
        self.assertEqual(set(variables), expected)
        for name, reference in variables.items():
            self.assertEqual(reference, {'name': 'mlflow-db84-secret', 'key': name})
        self.assertNotIn('Secret', resources)  # Applying a manifest must never clear stored credentials.
        self.assertIn('--log-bin-trust-function-creators=1', container['args'])
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        self.assertEqual(resources['Service']['spec']['selector'], pod['metadata']['labels'])
        claim = resources['PersistentVolumeClaim']
        volume = resources['PersistentVolume']
        self.assertEqual(claim['spec']['volumeName'], volume['metadata']['name'])
        self.assertNotEqual(claim['metadata']['name'], 'mlflow-db-pv-claim')
        self.assertEqual(pod['spec']['volumes'][0]['persistentVolumeClaim']['claimName'], claim['metadata']['name'])
        self.assertEqual(volume['spec']['persistentVolumeReclaimPolicy'], 'Retain')
        self.assertEqual(volume['spec']['accessModes'], ['ReadWriteOnce'])
        self.assertNotIn('namespace', volume['metadata'])

    def test_image_lock_and_fail_closed(self):
        lock = json.loads((ROOT / 'versions.lock.json').read_text())
        for source, immutable in lock['images'].items():
            self.assertRegex(immutable, r'@sha256:[a-f0-9]{64}$')
            rendered = yaml.safe_load(renderer.render('image: ' + source, lock['images']))
            self.assertEqual(rendered['image'], immutable)
        with self.assertRaises(ValueError):
            renderer.render('image: missing.example/application:unreviewed', lock['images'])

    def test_python_locks_and_bootstrap_consistency(self):
        paths = ['docker-images/etl-base-image/requirements.txt', 'airflow/image/requirements.txt',
                 'jupyterhub/images/hub/requirements.txt', 'superset/requirements.lock']
        for path in paths:
            text = (ROOT / path).read_text()
            entries = re.findall(r'^([\w.\-]+(?:\[[^\]]+\])?==[^\n]+(?:\n\s+--hash=[^\n]+)+)', text, re.M)
            packages = re.findall(r'^[a-zA-Z0-9_.-]+(?:\[[^\]]+\])?==', text, re.M)
            self.assertEqual(len(entries), len(packages), path)
            self.assertTrue(packages)
        values = yaml.safe_load((ROOT / 'superset/values.yaml').read_text())
        self.assertEqual(values['extraConfigs']['requirements.lock'], (ROOT / 'superset/requirements.lock').read_text())
        self.assertIn('--require-hashes', values['bootstrapScript'])
        self.assertFalse(values['supersetWebsockets']['enabled'])
        self.assertNotEqual(values['supersetWebsockets']['image']['tag'], 'latest')

    @unittest.skipUnless(os.environ.get('ALIAS_CHARTS_DIR') and os.environ.get('ALIAS_HELM'),
                         'Set ALIAS_CHARTS_DIR and ALIAS_HELM to verified local chart archives and Helm')
    def test_all_chart_images_including_hooks(self):
        charts = json.loads((ROOT / 'versions.lock.json').read_text())['charts']
        for name, chart in charts.items():
            with self.subTest(chart=name):
                archive = Path(os.environ['ALIAS_CHARTS_DIR']) / (name + '.tgz')
                import hashlib
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), chart['digest'])
                if name in ('openmetadata', 'trino'):
                    temporary = tempfile.TemporaryDirectory(prefix='alias-om-chart-')
                    self.addCleanup(temporary.cleanup)
                    patched = Path(temporary.name) / 'pinned.tgz'
                    subprocess.run([sys.executable, str(ROOT / 'scripts' / ('prepare-' + name + '-chart.py')),
                                    str(archive), str(patched)], check=True)
                    archive = patched
                args = [os.environ['ALIAS_HELM'], 'template', name, str(archive), '--namespace', name,
                        '--kube-version', '1.34.13', '--post-renderer', str(ROOT / 'scripts/locked-images.py')]
                values = ROOT / name / 'values.yaml'
                if values.exists():
                    args += ['-f', str(values)]
                # Pre-generated synthetic, credential-free runtime overrides from test_runtime.
                runtime = Path(os.environ['ALIAS_CHARTS_DIR']) / (name + '.values.json')
                if runtime.exists():
                    args += ['-f', str(runtime)]
                args += ['-f', str(ROOT / 'versions' / (name + '.values.json'))]
                if name == 'rancher':
                    args += ['--set', 'hostname=alias.example']
                p = subprocess.run(args, capture_output=True, text=True, check=True)
                def inspect(value):
                    if isinstance(value, dict):
                        if isinstance(value.get('image'), str):
                            self.assertRegex(value['image'], r'@sha256:[a-f0-9]{64}$')
                        for item in value.values():
                            inspect(item)
                    elif isinstance(value, list):
                        for item in value:
                            inspect(item)
                for doc in yaml.safe_load_all(p.stdout):
                    inspect(doc)


if __name__ == '__main__':
    unittest.main()
