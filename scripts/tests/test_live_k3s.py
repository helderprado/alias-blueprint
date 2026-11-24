"""Opt-in real installation/communication test; requires a working Docker daemon."""
import json
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('live_smoke', ROOT / 'scripts/local-smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@unittest.skipUnless(os.environ.get('ALIAS_RUN_K3S_E2E') == '1',
                     'Set ALIAS_RUN_K3S_E2E=1 to install K3s and exercise real Kubernetes services')
class LiveK3sTests(unittest.TestCase):
    def test_article_installer_and_service_operations(self):
        components = os.environ.get('ALIAS_E2E_COMPONENTS', 'local')
        result = subprocess.run(['bash', str(ROOT / 'install-k3s.sh'), '--smoke', '--test-host', 'docker',
                                 '--components', components, '--timeout', '600'],
                                cwd=ROOT, text=True, capture_output=True,
                                timeout=int(os.environ.get('ALIAS_E2E_TIMEOUT', '7200')))
        locations = re.findall(r'^Host report: (.+)$', result.stdout, re.M)
        self.assertTrue(locations, result.stderr[-3000:] + result.stdout[-3000:])
        path = Path(locations[-1])
        host = json.loads(path.read_text())
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])
        self.assertEqual(host['exit_code'], 0)
        self.assertTrue(host['test_host_removed'])
        self.assertEqual(len(host['reports']), 1)
        report = json.loads((path.parent / host['reports'][0]).read_text())
        self.assertTrue(report['cluster']['installer_verified'])
        statuses = {row['component']: row['status'] for row in report['checks']}
        requested = smoke.selection(components)
        for name in ['install-k3s', *requested, 'cleanup']:
            self.assertEqual(statuses[name], 'PASS', report)
        self.assertFalse(any(row['status'] != 'PASS' for row in report['checks']), report)
        print('Live smoke report: ' + str(path.parent / host['reports'][0]), flush=True)


if __name__ == '__main__':
    unittest.main()
