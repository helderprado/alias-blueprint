#!/usr/bin/env bash
# Read committed versions; never query a release channel at deployment time.
VERSIONS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
chart_version() {
    python3 - "$VERSIONS_ROOT/versions.lock.json" "$1" <<'PYTHON'
import json, sys
with open(sys.argv[1]) as stream:
    print(json.load(stream)['charts'][sys.argv[2]]['version'])
PYTHON
}
