"""Exercise the real article shell entrypoint with a fake network/installer boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class InstallK3sTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.bin = self.path / 'bin'
        self.bin.mkdir()
        self.env_file = self.path / 'empty.env'
        self.env_file.write_text('')
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('K3S_', 'INSTALL_K3S_', 'ALIAS_'))}
        self.env.update(PATH=str(self.bin) + ':' + os.environ['PATH'],
                        ALIAS_ENV_FILE=str(self.env_file), K3S_TEST_DIR=str(self.path))
        self.upstream = '''#!/bin/sh
python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path
p = Path(os.environ['K3S_TEST_DIR'])
(p/'executed.json').write_text(json.dumps({'args': sys.argv[1:], 'version': os.environ['INSTALL_K3S_VERSION']}))
sys.exit(int(os.environ.get('K3S_TEST_UPSTREAM_EXIT', '0')))
PY
'''
        (self.path / 'upstream.sh').write_text(self.upstream)
        self.executable('curl', '''import json, os, sys
from pathlib import Path
p = Path(os.environ['K3S_TEST_DIR'])
args = sys.argv[1:]
(p/'curl.json').write_text(json.dumps(args))
destination = Path(args[args.index('--output') + 1])
mode = os.environ.get('K3S_TEST_DOWNLOAD', 'ok')
destination.write_text('' if mode == 'empty' else (p/'upstream.sh').read_text())
sys.exit(22 if mode == 'partial-failure' else 0)
''')

    def executable(self, name, body):
        file = self.bin / name
        file.write_text('#!' + sys.executable + '\n' + body)
        file.chmod(0o700)

    def run_script(self, *args, **environment):
        return subprocess.run(['bash', str(ROOT / 'install-k3s.sh'), *args],
                              env=self.env | environment, text=True, capture_output=True)

    def test_default_installer_forwards_locked_version_cluster_init_and_article_config(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        called = json.loads((self.path / 'executed.json').read_text())
        self.assertEqual(called['version'], json.loads((ROOT / 'versions.lock.json').read_text())['k3s'])
        self.assertEqual(called['args'], ['server', '--cluster-init', '--config', str(ROOT / 'k3s-config.yaml')])
        downloaded = json.loads((self.path / 'curl.json').read_text())
        self.assertIn('https://get.k3s.io', downloaded)
        self.assertIn('=https', downloaded)
        self.assertFalse(Path(downloaded[downloaded.index('--output') + 1]).exists())
        config = yaml.safe_load((ROOT / 'k3s-config.yaml').read_text())
        self.assertEqual(config['service-node-port-range'], '1000-32767')
        self.assertNotIn('kube-apiserver-args', config)

    def test_explicit_version_and_config_with_spaces_are_forwarded_without_splitting(self):
        config = self.path / 'directory with spaces' / 'cluster config.yaml'
        config.parent.mkdir()
        config.write_text('service-node-port-range: 1000-32767\n')
        result = self.run_script(K3S_VERSION='v1.34.12+k3s1', K3S_CONFIG=str(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        called = json.loads((self.path / 'executed.json').read_text())
        self.assertEqual(called['version'], 'v1.34.12+k3s1')
        self.assertEqual(called['args'][-1], str(config))

    def test_bad_version_missing_config_and_unknown_arguments_never_contact_network(self):
        for environment in ({'K3S_VERSION': 'latest'}, {'K3S_VERSION': 'v1.34'},
                            {'K3S_CONFIG': str(self.env_file)},
                            {'K3S_CONFIG': str(self.path / 'missing.yaml')}):
            with self.subTest(environment=environment):
                self.assertNotEqual(self.run_script(**environment).returncode, 0)
                self.assertFalse((self.path / 'curl.json').exists())
        self.assertNotEqual(self.run_script('--unknown').returncode, 0)
        self.assertFalse((self.path / 'curl.json').exists())

    def test_empty_or_partial_failed_download_is_never_executed(self):
        for mode in ('empty', 'partial-failure'):
            with self.subTest(mode=mode):
                result = self.run_script(K3S_TEST_DOWNLOAD=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.path / 'executed.json').exists())
                args = json.loads((self.path / 'curl.json').read_text())
                self.assertFalse(Path(args[args.index('--output') + 1]).exists())

    def test_upstream_failure_is_not_reported_as_success(self):
        result = self.run_script(K3S_TEST_UPSTREAM_EXIT='31')
        self.assertEqual(result.returncode, 31)

    def test_smoke_mode_delegates_to_runner_that_tests_this_same_entrypoint(self):
        self.executable('python3', '''import json, os, sys
from pathlib import Path
(Path(os.environ['K3S_TEST_DIR'])/'runner.json').write_text(json.dumps(sys.argv[1:]))
''')
        result = self.run_script('--smoke', '--components', 'storage')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads((self.path / 'runner.json').read_text())
        self.assertEqual(args, [str(ROOT / 'scripts/local-smoke.py'), '--run', '--components', 'storage'])
        self.assertFalse((self.path / 'curl.json').exists())


if __name__ == '__main__':
    unittest.main()
