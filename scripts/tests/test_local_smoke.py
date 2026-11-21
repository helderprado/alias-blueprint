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
        with patch.object(lab, 'preflight', side_effect=smoke.Blocked('Docker unavailable')), \
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

    def test_broken_api_during_bootstrap_still_disposes_owned_container(self):
        lab = self.lab('storage')
        def bootstrap():
            lab.created = True
            raise RuntimeError('API never ready')
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'diagnostics', side_effect=RuntimeError('API unreachable')), \
                patch.object(lab, 'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        command.assert_called_once_with(['docker', 'rm', '--force', '--volumes', lab.name])

    def test_retention_and_explicit_cleanup_verify_container_ownership(self):
        lab = self.lab('storage', keep=True)
        def bootstrap():
            lab.created = True
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'storage'), patch.object(lab, 'release_unused'), \
                patch.object(lab, 'diagnostics'), patch.object(lab, 'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 0)
        command.assert_not_called()
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'wrong-owner\n')) as run:
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

    def test_failed_probe_restores_kernel_setting_before_container_removal(self):
        lab = self.lab('storage')
        def bootstrap():
            lab.created = True
            lab.previous_map_count = 65530
        with patch.object(lab, 'preflight'), patch.object(lab, 'bootstrap', side_effect=bootstrap), \
                patch.object(lab, 'storage', side_effect=RuntimeError('probe failed')), \
                patch.object(lab, 'release_unused'), patch.object(lab, 'diagnostics'), \
                patch.object(lab, 'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(lab.run(), 1)
        self.assertEqual(command.call_args_list[0].args[0],
                         ['docker', 'exec', lab.name, 'sysctl', '-w', 'vm.max_map_count=65530'])
        self.assertEqual(command.call_args_list[1].args[0], ['docker', 'rm', '--force', '--volumes', lab.name])

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
