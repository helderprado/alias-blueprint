import socket
import ssl

# Equivalent to curl --resolve: retain the configured TLS hostname/SNI while
# routing this isolated probe to the internal Kubernetes Service.
original_resolver = socket.getaddrinfo
def cluster_resolver(host, *args, **kwargs):
    if host == 'rancher.local.test':
        host = 'rancher.cattle-system.svc.cluster.local'
    return original_resolver(host, *args, **kwargs)
socket.getaddrinfo = cluster_resolver
context = ssl.create_default_context(cadata=SMOKE['ca'])
base = 'https://rancher.local.test'
wait_for(lambda: request(base + '/ping', context=context) == 'pong', 'Rancher verified HTTPS')
login = wait_for(lambda: request(base + '/v3-public/localProviders/local?action=login', 'POST',
                {'username': 'admin', 'password': SMOKE['password'], 'responseType': 'json'}, context=context), 'Rancher bootstrap authentication')
headers = {'Authorization': 'Bearer ' + login['token']}
clusters = request(base + '/v3/clusters', headers=headers, context=context)
assert any(cluster.get('id') == 'local' for cluster in clusters['data']), clusters
print('PASS: Rancher verified HTTPS, bootstrap login and local cluster API; external routing excluded')
