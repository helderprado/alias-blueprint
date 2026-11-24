import base64
import ssl

context = ssl.create_default_context(cadata=SMOKE['ca'])
headers = {'X-Trino-User': SMOKE['user'], 'Content-Type': 'text/plain',
           'Authorization': 'Basic ' + base64.b64encode((SMOKE['user'] + ':' + SMOKE['password']).encode()).decode()}
base = 'https://trino.trino.svc.cluster.local:8443'
def query(sql):
    result = request(base + '/v1/statement', 'POST', sql.encode(), headers, context)
    rows = result.get('data', [])
    deadline = time.monotonic() + SMOKE['timeout']
    while result.get('nextUri'):
        if time.monotonic() >= deadline:
            raise RuntimeError('Trino query exceeded deadline')
        result = request(result['nextUri'], headers=headers, context=context)
        rows.extend(result.get('data', []))
        time.sleep(0.1)
    if result.get('error'):
        raise RuntimeError('Trino query failed: ' + result['error'].get('message', '') +
                           ' [' + result['error'].get('errorName', '') + ']')
    return rows
assert query('SELECT count(*) FROM tpch.tiny.nation') == [[25]]
assert query('SELECT count(*), sum(amount) FROM pinot.default.alias_smoke') == [[3, 60]]
print('PASS: Trino authenticated TLS queries, TPC-H count=25 and Pinot count=3/sum=60')
