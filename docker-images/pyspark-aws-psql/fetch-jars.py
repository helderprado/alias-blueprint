"""Download only locked artifacts, verify bytes before adding them to Spark's classpath."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen


def install(lock_path, destination):
    lock = json.loads(Path(lock_path).read_text())
    destination = Path(destination)
    version = lock['hadoop_runtime']
    for library in ('hadoop-client-api', 'hadoop-client-runtime'):
        if not (destination / (library + '-' + version + '.jar')).is_file():
            raise ValueError('Base image must provide the locked Hadoop client runtime: ' + library)
    for artifact in lock['artifacts']:
        target = destination / artifact['file']
        if target.name != artifact['file']:
            raise ValueError('Artifact file must be a basename')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError('Existing JAR differs from the lock: ' + artifact['file'])
            continue
        with tempfile.NamedTemporaryFile(dir=destination, delete=False) as output:
            candidate = Path(output.name)
            digest = hashlib.sha256()
            try:
                with urlopen(artifact['url'], timeout=90) as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        output.write(chunk)
                output.close()
                if digest.hexdigest() != artifact['sha256']:
                    raise ValueError('JAR SHA-256 mismatch: ' + artifact['file'])
                candidate.chmod(0o644)
                candidate.replace(target)
            finally:
                candidate.unlink(missing_ok=True)


if __name__ == '__main__':
    install(sys.argv[1], sys.argv[2])
