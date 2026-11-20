"""Focused offline deployment/configuration check for the two query services."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import trino_security as security
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'scripts/runtime-secrets.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class QueryServicesTests(unittest.TestCase):
    def test_independent_profiles_and_real_charts(self):
        chart_dir, helm = os.environ.get('ALIAS_CHARTS_DIR'), os.environ.get('ALIAS_HELM')
        with tempfile.TemporaryDirectory(prefix='alias-query-') as name:
            directory = Path(name)
            env = {'TRINO_USER': 'query-user', 'TRINO_PASSWORD': 'Synthetic-Query-Password-123',
                   'TRINO_SHARED_SECRET': 'a' * 64}
            with patch.object(security, 'ROOT', directory), patch.dict(os.environ, env, clear=True):
                security.bootstrap()
                original = {f: (directory / 'trino/runtime-creds' / f).read_bytes() for f in security.FILES}
                security.bootstrap()
                self.assertEqual(original, {f: (directory / 'trino/runtime-creds' / f).read_bytes() for f in security.FILES})
                secrets, trino_values = runtime.build('trino')
                self.assertEqual(len(secrets), 3)
                self.assertNotIn(env['TRINO_PASSWORD'], json.dumps(secrets) + json.dumps(trino_values))
                catalog_file = directory / 'catalogs.json'
                catalog_file.write_text(json.dumps({'tpch': 'connector.name=tpch\n'}))
                with patch.dict(os.environ, {'TRINO_CATALOGS_FILE': str(catalog_file)}):
                    configured_secrets, configured_values = runtime.build('trino')
                    self.assertEqual(configured_secrets[-1]['metadata']['name'], 'trino-catalogs')
                    self.assertEqual(configured_values['secretMounts'][-1]['path'], '/etc/trino/secret-catalogs')
                with patch.dict(os.environ, {'TRINO_PASSWORD': 'changed-synthetic-password'}), self.assertRaises(ValueError):
                    security.material()
            with patch.dict(os.environ, {}, clear=True):
                secrets, pinot_values = runtime.build('pinot')
                self.assertEqual(secrets, [])
                self.assertNotIn('zookeeper', pinot_values)  # Chart's independent persistent bundle remains active.
                policy = runtime.query_network_policy('pinot')
                self.assertEqual(policy['spec']['ingress'], [{'from': [{'podSelector': {}}]}])
                with patch.dict(os.environ, {'PINOT_ALLOWED_NAMESPACES': 'trino', 'PINOT_ZOOKEEPER_URL': 'zookeeper.example:2181/pinot'}):
                    _, external = runtime.build('pinot')
                    self.assertFalse(external['zookeeper']['enabled'])
                    rules = runtime.query_network_policy('pinot')['spec']['ingress'][1]
                    self.assertEqual({p['port'] for p in rules['ports']}, {9000, 8099})
                # A no-Secret component must never list all namespace Secrets.
                with patch.object(sys, 'argv', ['runtime', 'pinot', str(directory / 'pinot.json')]), patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(stdout='')) as run:
                    runtime.main()
                    self.assertEqual(run.call_count, 2)
                    self.assertTrue(all(c.args[0] == ['kubectl', 'apply', '-f', '-'] for c in run.call_args_list))
            if chart_dir and helm:
                for component, values in [('trino', trino_values), ('pinot', pinot_values)]:
                    path = directory / (component + '.json')
                    path.write_text(json.dumps(values))
                    archive = Path(chart_dir) / (component + '.tgz')
                    if component == 'trino':
                        prepared = directory / 'trino-pinned.tgz'
                        subprocess.run([sys.executable, str(ROOT / 'scripts/prepare-trino-chart.py'), str(archive), str(prepared)], check=True)
                        archive = prepared
                    result = subprocess.run([helm, 'template', component, str(archive), '--namespace', component,
                        '--kube-version', '1.34.13', '-f', str(ROOT / component / 'values.yaml'), '-f', str(path),
                        '-f', str(ROOT / 'versions' / (component + '.values.json')),
                        '--post-renderer', str(ROOT / 'scripts/locked-images.py')], check=True, capture_output=True, text=True)
                    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
                    workloads = [d for d in docs if d['kind'] in ('Deployment', 'StatefulSet')]
                    self.assertTrue(workloads)
                    for doc in workloads:
                        pod = doc['spec']['template']['spec']
                        for container in pod.get('containers', []) + pod.get('initContainers', []):
                            self.assertRegex(container['image'], r'@sha256:[a-f0-9]{64}$')
                    self.assertTrue(all(d['spec'].get('type', 'ClusterIP') == 'ClusterIP' for d in docs if d['kind'] == 'Service'))
                    self.assertNotIn(env['TRINO_PASSWORD'], result.stdout)
                    self.assertNotIn(env['TRINO_SHARED_SECRET'], result.stdout)
                    if component == 'pinot':
                        self.assertGreaterEqual(sum(bool(d['spec'].get('volumeClaimTemplates')) for d in workloads), 3)
                        self.assertTrue(any('zookeeper' in d['metadata']['name'] for d in workloads))


if __name__ == '__main__':
    unittest.main()
