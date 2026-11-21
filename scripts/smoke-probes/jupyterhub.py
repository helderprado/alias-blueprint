base = 'http://127.0.0.1:8081/hub/api'
headers = {'Authorization': 'token ' + SMOKE['token']}
request(base + '/users/smoke', 'POST', {}, headers)
request(base + '/users/smoke/server', 'POST', {}, headers)
def ready():
    user = request(base + '/users/smoke', headers=headers)
    return user.get('servers', {}).get('', {}).get('ready')
wait_for(ready, 'JupyterHub notebook spawn')
print('PASS: authenticated Hub API created a user and started a ready notebook')
