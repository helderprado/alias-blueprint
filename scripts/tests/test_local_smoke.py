"""Runner failure semantics, isolation and coverage; no running services implied."""
import argparse
import base64
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_smoke', ROOT / 'scripts/local-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class LocalSmokeTests(unittest.TestCase):
    def lab(self, components='all', keep=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        args = argparse.Namespace(mode='run', components=components, timeout=30, build_timeout=60, keep=keep)
        lab = smoke.Lab(args)
        lab.path = Path(directory.name) / 'run'
        lab.project = lab.path / 'project'
        lab.bin = lab.path / 'bin'
        return lab

    def test_dependency_closure_is_ordered_and_complete(self):
        stages = smoke.selection('superset,airflow')
        for name in stages:
            for dependency in smoke.STAGES[name]:
                self.assertLess(stages.index(dependency), stages.index(name))
        self.assertTrue({'databases', 'registry', 'minio', 'spark', 'pinot', 'trino'} <= set(stages))
        self.assertNotIn('rancher', stages)
        with self.assertRaises(ValueError):
            smoke.selection('unknown')

    def test_unavailable_runtime_reports_not_run_and_nonzero(self):
        lab = self.lab()
        with patch.object(lab, 'preflight', side_effect=smoke.Blocked('Administrator access unavailable')), \
                patch.object(lab, 'bootstrap') as bootstrap, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        bootstrap.assert_not_called()
        report = json.loads((lab.path / 'report.json').read_text())
        self.assertEqual(report['checks'][0]['status'], 'BLOCKED')
        self.assertTrue(all(row['status'] == 'NOT_RUN' for row in report['checks'][1:-1]))
        self.assertEqual((lab.path / 'report.json').stat().st_mode & 0o777, 0o600)

    def test_failed_stage_blocks_dependents_but_runs_independent_stage(self):
        lab = self.lab('registry,opensearch')
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap'), \
                patch.object(lab, 'storage', side_effect=RuntimeError('PVC failed')), \
                patch.object(lab, 'registry') as registry, patch.object(lab, 'opensearch') as search, \
                patch.object(lab, 'diagnostics'), patch.object(lab, 'release_unused'), redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        registry.assert_not_called()
        search.assert_called_once()
        statuses = {row['component']: row['status'] for row in lab.rows}
        self.assertEqual(statuses['storage'], 'FAIL')
        self.assertEqual(statuses['registry'], 'BLOCKED')
        self.assertEqual(statuses['opensearch'], 'PASS')

    def test_broken_api_during_bootstrap_still_requests_owned_namespace_cleanup(self):
        lab = self.lab('storage')
        def bootstrap():
            lab.created = True
            raise RuntimeError('API never ready')
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'diagnostics', side_effect=RuntimeError('API unreachable')), \
                patch.object(lab, 'cleanup_workloads') as cleanup, \
                patch.object(lab, 'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        cleanup.assert_called_once()
        command.assert_not_called()  # Never uninstall the article's system service.

    def test_retention_and_explicit_cleanup_verify_cluster_ownership(self):
        lab = self.lab('storage', keep=True)
        def bootstrap():
            lab.created = True
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'storage'), patch.object(lab, 'release_unused'), \
                patch.object(lab, 'diagnostics'), patch.object(lab, 'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 0)
        command.assert_not_called()
        smoke.private(lab.path / 'native.json', json.dumps({'k3s': '/test/k3s', 'namespaces': ['storage']}))
        with patch.object(smoke, 'STATE', lab.path.parent.parent), \
                patch.object(Path, 'read_text', return_value=json.dumps({'k3s': '/test/k3s', 'namespaces': ['storage']})), \
                patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"metadata":{"labels":{}}}')) as run:
            with self.assertRaisesRegex(ValueError, 'ownership'):
                smoke.cleanup(lab.id)
            self.assertEqual(run.call_count, 1)
        with patch.object(subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                smoke.cleanup('../../existing-cluster')
            run.assert_not_called()

    def test_generated_secrets_are_redacted_and_existing_kubeconfig_is_ignored(self):
        with patch.dict(smoke.os.environ, {'KUBECONFIG': '/existing/config', 'MLFLOW_DB_PASSWORD': 'existing-password'}):
            lab = self.lab()
        self.assertNotEqual(lab.env['KUBECONFIG'], '/existing/config')
        self.assertNotIn('MLFLOW_DB_PASSWORD', lab.env)
        token = lab.token()
        encoded = base64.b64encode(token.encode()).decode()
        self.assertEqual(lab.clean(token + ' ' + encoded), '[REDACTED] [REDACTED]')

    def test_sensitive_reads_are_available_to_caller_but_never_logged(self):
        lab = self.lab()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'private-key-material', '')):
            output = lab.command(['read-test-secret'], sensitive=True)
        self.assertEqual(output, 'private-key-material')
        self.assertNotIn(output, (lab.path / 'logs/preflight.log').read_text())

    def test_native_bootstrap_executes_article_entrypoint_and_preserves_its_options(self):
        lab = self.lab('storage')
        lab.path.mkdir()
        lab.bin.mkdir()
        lab.env['KUBECONFIG'] = str(lab.path / 'kubeconfig')
        lab.values.update(REGISTRY_USER='synthetic', REGISTRY_PASSWORD='synthetic-password')
        base = yaml.safe_load((ROOT / 'k3s-config.yaml').read_text())
        def command(args, **kwargs):
            if args[0] == lab.py:
                return json.dumps(base)
            if args[0] == 'systemctl':
                return 'active\n'
            if '--version' in args:
                return 'k3s version ' + lab.lock['k3s'] + ' (test)\n'
            return ''
        def privileged(args, **kwargs):
            return 'apiVersion: v1\n' if args[0] == 'cat' else ''
        with patch.object(lab, 'tools'), patch.object(lab, 'snapshot'), patch.object(lab, 'command', side_effect=command), \
                patch.object(lab, 'root_command', side_effect=privileged) as root, \
                patch.object(lab, 'k', return_value='{}'), redirect_stdout(io.StringIO()):
            lab.bootstrap()
        install = root.call_args_list[0].args[0]
        self.assertEqual(install[-2:], ['bash', str(ROOT / 'install-k3s.sh')])
        self.assertIn('K3S_VERSION=' + lab.lock['k3s'], install)
        effective = json.loads((lab.path / 'k3s-config.yaml').read_text())
        for key, value in base.items():
            self.assertEqual(effective[key], value)
        self.assertNotIn('disable', effective)  # Preserve article defaults such as Traefik.
        self.assertTrue(any(row['component'] == 'install-k3s' and row['status'] == 'PASS' for row in lab.rows))

    def test_failed_probe_restores_kernel_setting_before_namespace_cleanup(self):
        lab = self.lab('storage')
        def bootstrap():
            lab.created = True
            lab.previous_map_count = 65530
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'storage', side_effect=RuntimeError('probe failed')), \
                patch.object(lab, 'release_unused'), patch.object(lab, 'diagnostics'), \
                patch.object(lab, 'cleanup_workloads') as cleanup, \
                patch.object(lab, 'root_command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        self.assertEqual(command.call_args_list[0].args[0],
                         ['sysctl', '-w', 'vm.max_map_count=65530'])
        cleanup.assert_called_once()

    def test_probe_sources_and_scheduled_dag_compile(self):
        common = (ROOT / 'scripts/smoke-probes/common.py').read_text()
        for probe in (ROOT / 'scripts/smoke-probes').glob('*.py'):
            compile('SMOKE = {}\n' + common + '\n' + probe.read_text(), str(probe), 'exec')
        lab = self.lab('airflow')
        lab.spark_template = {'metadata': {'name': 'synthetic'}, 'spec': {}}
        lab.path.mkdir()
        maps = []
        with patch.object(lab, 'spark_binding'), patch.object(lab, 'configmap', side_effect=lambda *args: maps.append(args)), \
                patch.object(lab, 'deploy'), patch.object(lab, 'probe'):
            lab.airflow()
        compile(maps[0][2]['alias_smoke.py'], 'alias_smoke.py', 'exec')


if __name__ == '__main__':
    unittest.main()
