import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote

environment = dict(os.environ, MC_HOST_smoke='http://' + quote(SMOKE['access']) + ':' + quote(SMOKE['secret']) + '@127.0.0.1:9000')
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'source'
    target = Path(directory) / 'target'
    source.write_bytes(b'ALIAS synthetic object\n')
    def mc(*args):
        subprocess.run(['mc', '--config-dir', directory, *args], env=environment, check=True, capture_output=True)
    mc('cp', str(source), 'smoke/mlflow/alias-smoke/object')
    mc('cp', 'smoke/mlflow/alias-smoke/object', str(target))
    assert source.read_bytes() == target.read_bytes(), 'S3 round trip changed the object'
    mc('rm', 'smoke/mlflow/alias-smoke/object')
print('PASS: scoped S3 upload/download/delete')
