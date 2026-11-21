import http.cookiejar
import re
import psycopg

base = 'http://127.0.0.1:80'
cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
def login():
    with opener.open(base + '/login', timeout=30) as response:
        page = response.read().decode()
    csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
    assert csrf, 'pgAdmin login form has no CSRF token'
    body = urllib.parse.urlencode({'email': 'smoke@local.test', 'password': SMOKE['password'],
                                 'csrf_token': csrf.group(1)}).encode()
    with opener.open(urllib.request.Request(base + '/login', data=body), timeout=30) as response:
        assert '/login' not in response.url, 'pgAdmin login failed'
    return True
wait_for(login, 'pgAdmin login')
servers = json.load(open('/pgadmin4/servers.json'))
server = servers['Servers']['1']
with psycopg.connect(host=server['Host'], port=server['Port'], dbname=server['MaintenanceDB'],
                     user=server['Username'], password=SMOKE['db_password']) as connection:
    assert connection.execute('SELECT 42').fetchone() == (42,)
print('PASS: pgAdmin login, configured server and PostgreSQL connection from pgAdmin Pod')
