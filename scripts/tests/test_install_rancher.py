"""Exercise initial/repeated namespace creation without Kubernetes or network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallRancherTests(unittest.TestCase):
    def test_install_creates_namespaces_and_rerun_reuses_them(self):
        with tempfile.TemporaryDirectory(prefix='alias-rancher-test-') as directory:
            directory = Path(directory)
            state = directory / 'namespaces.json'
            state.write_text('[]')
            stub = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == 'kubectl':
    assert args[0] == 'apply', 'Do not create namespaces non-idempotently'
elif args[0] == 'upgrade':
    path = pathlib.Path(os.environ['TEST_NAMESPACES'])
    namespaces = json.loads(path.read_text())
    namespace = args[args.index('--namespace') + 1]
    assert '--install' in args
    assert '--create-namespace' in args, 'Missing create-namespace: ' + namespace
    if namespace not in namespaces:
        namespaces.append(namespace)
    path.write_text(json.dumps(namespaces))
'''
            for name in ('helm', 'kubectl'):
                program = directory / name
                program.write_text(stub)
                program.chmod(0o700)
            env = dict(os.environ, PATH=str(directory) + ':' + os.environ['PATH'], TEST_NAMESPACES=str(state))
            for _ in range(2):
                run = subprocess.run(['bash', str(ROOT / 'install-rancher.sh')], cwd=directory,
                                     env=env, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(set(json.loads(state.read_text())), {'cert-manager', 'cattle-system'})


if __name__ == '__main__':
    unittest.main()
