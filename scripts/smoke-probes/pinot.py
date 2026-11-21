base = 'http://pinot-controller.pinot.svc.cluster.local:9000'
request(base + '/schemas', 'POST', {'schemaName': 'alias_smoke',
    'dimensionFieldSpecs': [{'name': 'id', 'dataType': 'INT'}],
    'metricFieldSpecs': [{'name': 'amount', 'dataType': 'INT'}]})
request(base + '/tables', 'POST', {'tableName': 'alias_smoke', 'tableType': 'OFFLINE',
    'segmentsConfig': {'schemaName': 'alias_smoke', 'replication': '1'},
    'tableIndexConfig': {'loadMode': 'MMAP'},
    'tenants': {'broker': 'DefaultTenant', 'server': 'DefaultTenant'}, 'metadata': {}})
boundary = 'alias_smoke_boundary'
rows = '\n'.join(json.dumps({'id': n, 'amount': n * 10}) for n in (1, 2, 3))
body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="data.json"\r\n'
        'Content-Type: application/json\r\n\r\n' + rows + '\r\n--' + boundary + '--\r\n').encode()
query = urllib.parse.urlencode({'tableNameWithType': 'alias_smoke_OFFLINE', 'batchConfigMapStr': '{"inputFormat":"json"}'})
request(base + '/ingestFromFile?' + query, 'POST', body, {'Content-Type': 'multipart/form-data; boundary=' + boundary})
def query_rows():
    result = request('http://pinot-broker.pinot.svc.cluster.local:8099/query/sql', 'POST',
                     {'sql': 'SELECT count(*), sum(amount) FROM alias_smoke'})
    assert not result.get('exceptions'), result
    assert result['resultTable']['rows'] == [[3, 60]], result
    return True
wait_for(query_rows, 'Pinot ingestion and broker query')
print('PASS: Pinot ingestion and count=3, sum=60')
