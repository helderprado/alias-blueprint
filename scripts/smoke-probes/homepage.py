page = request('http://homepage.homepage.svc.cluster.local:3000')
assert isinstance(page, str) and '<html' in page.lower(), 'Homepage returned no HTML'
services = request('http://homepage.homepage.svc.cluster.local:3000/api/services')
assert 'PostgreSQL' in json.dumps(services) and 'Registry' in json.dumps(services), services
print('PASS: Homepage HTTP and configured local links')
