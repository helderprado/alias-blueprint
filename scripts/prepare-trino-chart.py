#!/usr/bin/env python3
"""Verify Trino's official chart and omit its upstream CI-only login test."""
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
    if hashlib.sha256(data).hexdigest() != lock['charts']['trino']['digest']:
        raise ValueError('Trino chart checksum does not match versions.lock.json')
    removed = False
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as original:
        with open(destination, 'wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as result:
                for item in original.getmembers():
                    if item.name == 'trino/templates/tests/test-connection.yaml':
                        removed = True
                        continue
                    result.addfile(item, original.extractfile(item) if item.isfile() else None)
    if not removed:
        raise ValueError('Expected upstream CI test not found; review the chart patch')


if __name__ == '__main__':
    try:
        prepare(*sys.argv[1:])
    except (ValueError, OSError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
