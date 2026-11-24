"""Shared stdlib HTTP helpers; prepended to probes executed inside test Pods."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def request(url, method='GET', payload=None, headers=None, context=None):
    headers = dict(headers or {})
    if payload is not None and not isinstance(payload, bytes):
        payload = json.dumps(payload).encode()
        headers.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as response:
            data = response.read().decode()
            try:
                return json.loads(data)
            except ValueError:
                return data
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors='replace')[:1200]
        for key, value in SMOKE.items():
            if isinstance(value, str) and value and any(part in key.lower() for part in ('password', 'secret', 'token')):
                detail = detail.replace(value, '[REDACTED]')
        error.msg = str(error.reason) + ': ' + detail
        raise


def wait_for(callback, label):
    deadline = time.monotonic() + SMOKE.get('timeout', 300)
    last = ''
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (OSError, ValueError, KeyError, AssertionError) as error:
            last = str(error)
        time.sleep(2)
    raise RuntimeError('Timed out waiting for ' + label + ': ' + last[-500:])
