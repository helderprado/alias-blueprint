"""Check credential generation without Docker or real authentication material."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class GeneratorTests(unittest.TestCase):
    def test_ignored_output_permissions_and_failure_preservation(self):
        with tempfile.TemporaryDirectory(prefix='alias-generator-') as name:
            root = Path(name)
            for file in ['registry/gen-pass.sh', 'scripts/env.sh', '.gitignore']:
                target = root / file
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / file, target)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            docker = bin_dir / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import os,sys
assert sys.argv[1:6]==['run','--rm','-i','--entrypoint','htpasswd']
assert sys.argv[6].startswith('httpd@sha256:')
assert sys.argv[7:]==['-Bni','image-reader']
assert sys.stdin.read().strip()==os.environ['REGISTRY_PASSWORD']
mode=os.environ.get('TEST_DOCKER_MODE')
if mode=='fail': sys.exit(1)
if mode!='empty': print('image-reader:synthetic-hash-output')
''')
            docker.chmod(0o700)
            password = secrets.token_urlsafe(24)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('REGISTRY_', 'ALIAS_ENV_'))}
            env.update(PATH=str(bin_dir) + ':' + env['PATH'], REGISTRY_USER='image-reader', REGISTRY_PASSWORD=password)
            script = root / 'registry/gen-pass.sh'
            def run(extra=None):
                return subprocess.run(['bash', str(script)], cwd='/tmp', env=env | (extra or {}), capture_output=True, text=True)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            output = root / 'registry/registry-creds/htpasswd'
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(password, output.read_text() + result.stdout + result.stderr)
            self.assertEqual([p.name for p in output.parent.iterdir()], ['htpasswd'])
            subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(output)], check=True)
            # A normal add does not stage the generated hash or environment input.
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files'], text=True)
            self.assertNotIn('registry-creds/', tracked)
            original = output.read_bytes()
            for mode in ['fail', 'empty']:
                self.assertNotEqual(run({'TEST_DOCKER_MODE': mode}).returncode, 0)
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual([p.name for p in output.parent.iterdir()], ['htpasswd'])
            # A broken ignore rule must stop before replacing the existing file.
            (root / '.gitignore').write_text('')
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
