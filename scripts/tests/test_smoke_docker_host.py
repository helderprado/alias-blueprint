"""The Docker host receives a source snapshot, never local credential artifacts."""
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('smoke_docker_host', ROOT / 'scripts/smoke_docker_host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class DockerSourceTests(unittest.TestCase):
    def test_snapshot_includes_current_sources_and_excludes_git_and_ignored_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('.env\nruntime-creds/\n.local-smoke/\n')
            (root / 'install-k3s.sh').write_text('original\n')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            (root / 'install-k3s.sh').write_text('current edit\n')
            (root / 'new-probe.py').write_text('new probe\n')
            (root / '.env').write_text('PRIVATE_PASSWORD=secret\n')
            for name in ('runtime-creds', '.local-smoke'):
                (root / name).mkdir()
                (root / name / 'private-key').write_text('secret')
            with patch.object(host, 'ROOT', root):
                data = host.source_archive()
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.getnames()), {'.gitignore', 'install-k3s.sh', 'new-probe.py'})
                self.assertEqual(archive.extractfile('install-k3s.sh').read(), b'current edit\n')


if __name__ == '__main__':
    unittest.main()
