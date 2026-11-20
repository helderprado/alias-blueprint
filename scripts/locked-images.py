#!/usr/bin/env python3
"""Helm post-renderer: replace known image tags with verified, committed digests."""
import json
from pathlib import Path
import re
import sys
import yaml


def render(text, images):
    documents = list(yaml.safe_load_all(text))
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('image'), str):
                image = value['image']
                if image in images:
                    value['image'] = images[image]
                elif not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', image):
                    raise ValueError('Image is absent from versions.lock.json: ' + image)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for doc in documents:
        visit(doc)
    return yaml.safe_dump_all(documents, sort_keys=False)


if __name__ == '__main__':
    try:
        lock = json.loads((Path(__file__).resolve().parents[1] / 'versions.lock.json').read_text())
        sys.stdout.write(render(sys.stdin.read(), lock['images']))
    except (ValueError, yaml.YAMLError) as error:
        print('Image lock validation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
