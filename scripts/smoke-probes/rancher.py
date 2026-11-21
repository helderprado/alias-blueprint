# Rancher terminates TLS at its ingress. This local profile has no ingress;
# its internal HTTP listener remains private to the dedicated cluster namespace.
base = 'http://rancher.cattle-system.svc.cluster.local'
assert request(base + '/ping') == 'pong'
login = request(base + '/v3-public/localProviders/local?action=login', 'POST',
                {'username': 'admin', 'password': SMOKE['password'], 'responseType': 'json'})
headers = {'Authorization': 'Bearer ' + login['token']}
clusters = request(base + '/v3/clusters', headers=headers)
assert any(cluster.get('id') == 'local' for cluster in clusters['data']), clusters
print('PASS: Rancher private HTTP readiness, bootstrap login and local cluster API; public TLS/routing excluded')
