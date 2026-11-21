import copy
import json
from pathlib import Path
import ssl
import time
import urllib.request

application = copy.deepcopy(SMOKE['application'])
directory = Path('/var/run/secrets/kubernetes.io/serviceaccount')
context = ssl.create_default_context(cafile=str(directory / 'ca.crt'))
headers = {'Authorization': 'Bearer ' + (directory / 'token').read_text().strip(), 'Content-Type': 'application/json'}
url = 'https://kubernetes.default.svc/apis/sparkoperator.k8s.io/v1beta2/namespaces/spark/sparkapplications'
def api(path='', method='GET', payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=context) as response:
        return json.load(response)
name = application['metadata']['name']
api(method='POST', payload=application)
deadline = time.monotonic() + SMOKE['timeout']
while time.monotonic() < deadline:
    resource = api('/' + name)
    state = resource.get('status', {}).get('applicationState', {}).get('state')
    if state == 'COMPLETED':
        api('/' + name, method='DELETE')
        print('PASS: distributed Spark job submitted by this service')
        break
    if state in ('FAILED', 'SUBMISSION_FAILED', 'FAILING'):
        raise RuntimeError('Spark job failed: ' + str(resource.get('status', {})))
    time.sleep(3)
else:
    raise RuntimeError('Spark job did not complete before deadline')
