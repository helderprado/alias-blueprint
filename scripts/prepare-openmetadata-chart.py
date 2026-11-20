#!/usr/bin/env python3
"""Verify the official chart, then pin its otherwise hardcoded Helm test image."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile


def prepare(source, destination):
    lock = json.loads((Path(__file__).resolve().parents[1] / 'versions.lock.json').read_text())
    data = Path(source).read_bytes()
    if hashlib.sha256(data).hexdigest() != lock['charts']['openmetadata']['digest']:
        raise ValueError('OpenMetadata chart checksum does not match versions.lock.json')
    pinned = lock['images']['busybox:1.38.0']
    changed = False
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as original:
        with open(destination, 'wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as result:
                for item in original.getmembers():
                    body = original.extractfile(item).read() if item.isfile() else None
                    entry = copy.copy(item)
                    if item.name == 'openmetadata/templates/tests/test-connection.yaml':
                        if b'image: busybox\n' not in body:
                            raise ValueError('Unexpected OpenMetadata Helm test template; review chart patch')
                        body = body.replace(b'image: busybox\n', ('image: ' + pinned + '\n').encode())
                        entry.size = len(body)
                        changed = True
                    result.addfile(entry, io.BytesIO(body) if body is not None else None)
    if not changed:
        raise ValueError('Expected OpenMetadata Helm test template was not found')


if __name__ == '__main__':
    try:
        prepare(*sys.argv[1:])
    except (ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
