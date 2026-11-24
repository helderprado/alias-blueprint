base = 'http://127.0.0.1:8081/hub/api'
headers = {'Authorization': 'token ' + SMOKE['token']}
try:
    user = request(base + '/users/smoke', headers=headers)
except urllib.error.HTTPError as error:
    if error.code != 404:
        raise
    user = request(base + '/users/smoke', 'POST', {}, headers)
if not user.get('servers', {}).get('', {}).get('ready'):
    request(base + '/users/smoke/server', 'POST', {}, headers)
def ready():
    user = request(base + '/users/smoke', headers=headers)
    return user.get('servers', {}).get('', {}).get('ready')
wait_for(ready, 'JupyterHub notebook spawn')
print('PASS: authenticated Hub API created a user and started a ready notebook')
