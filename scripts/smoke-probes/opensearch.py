import base64
import ssl

context = ssl.create_default_context(cadata=SMOKE['ca'])
authorization = base64.b64encode((SMOKE['user'] + ':' + SMOKE['password']).encode()).decode()
headers = {'Authorization': 'Basic ' + authorization}
base = 'https://opensearch.opensearch.svc.cluster.local:9200'
request(base + '/alias-smoke', 'PUT', {}, headers, context)
request(base + '/alias-smoke/_doc/1?refresh=true', 'PUT', {'message': 'synthetic audit'}, headers, context)
result = request(base + '/alias-smoke/_search', 'POST', {'query': {'match': {'message': 'audit'}}}, headers, context)
assert result['hits']['total']['value'] == 1, result
request(base + '/alias-smoke', 'DELETE', headers=headers, context=context)
print('PASS: OpenSearch TLS, authentication, indexing and search')
