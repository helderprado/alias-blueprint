#!/usr/bin/env python3
"""Test the article's native install-k3s.sh, then Kubernetes service operations."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local-smoke'
LABEL = 'org.alias-blueprint.local-smoke'
STAGES = {
    'storage': (), 'databases': (), 'registry': ('storage',),
    'minio': ('registry',), 'mlflow': ('databases', 'minio'),
    'spark': ('minio',), 'airflow': ('databases', 'spark'),
    'jupyterhub': ('spark',), 'opensearch': (),
    'openmetadata': ('databases', 'opensearch', 'mlflow'),
    'pinot': (), 'trino': ('pinot',), 'superset': ('databases', 'trino'),
    'pgadmin': ('databases',), 'homepage': (), 'cert-manager': (),
    'rancher': ('cert-manager',), 'glusterfs': (),
}
PURPOSES = {
    'storage': 'PVC: write in one Pod and read in another',
    'databases': 'PostgreSQL + MySQL: insert/select/delete synthetic rows',
    'registry': 'authenticated image push and Kubernetes pull/run',
    'minio': 'scoped S3 upload/download/delete, with persistence',
    'mlflow': 'MySQL + S3: run, metric, artifact and registered model',
    'spark': 'Spark Operator: distributed count + S3 Parquet round trip',
    'airflow': 'scheduler executes a DAG that submits and awaits a Spark job',
    'jupyterhub': 'Hub API spawns a notebook; notebook submits a Spark job',
    'opensearch': 'TLS/auth: index, search and delete synthetic document',
    'openmetadata': 'PostgreSQL + OpenSearch: import MLflow model through APIs, search catalog',
    'pinot': 'create schema/table, ingest 3 JSON rows and query broker',
    'trino': 'authenticated TLS SQL: synthetic catalog and Pinot connector',
    'superset': 'create Trino source, query Pinot, save dataset/chart/dashboard',
    'pgadmin': 'login page + PostgreSQL server registration and connection',
    'homepage': 'HTTP page and configured local service links',
    'cert-manager': 'issue a self-signed test certificate and verify readiness',
    'rancher': 'verified HTTPS readiness + bootstrap login + local cluster API',
    'glusterfs': 'BLOCKED locally: replicated profile requires 3 prepared hosts',
}


class Blocked(RuntimeError):
    pass


class ProbeFailed(RuntimeError):
    pass


def selection(value):
    requested = ([name for name in STAGES if name != 'glusterfs'] if value == 'local'
                 else list(STAGES) if value == 'all' else value.split(','))
    unknown = set(requested) - STAGES.keys()
    if unknown:
        raise ValueError('Unknown components: ' + ', '.join(sorted(unknown)))
    needed = set()
    def add(name):
        for dependency in STAGES[name]:
            add(dependency)
        needed.add(name)
    for name in requested:
        add(name)
    return [name for name in STAGES if name in needed]


def private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(data)
    path.chmod(0o600)


def download(url, target, digest=None):
    if target.exists() and digest and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return
    request = urllib.request.Request(url, headers={'User-Agent': 'ALIAS-Blueprint-local-smoke/1.0'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('SHA-256 mismatch: ' + url)
    private(target, '')
    target.write_bytes(data)


class Lab:
    def __init__(self, args):
        self.args = args
        resume = getattr(args, 'resume_run', None)
        if resume and not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{6}', resume):
            raise ValueError('Invalid resume run ID')
        self.id = resume or (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(3))
        self.name = 'alias-smoke-' + self.id.lower()
        self.path = STATE / 'runs' / self.id
        self.project = self.path / 'project'
        self.bin = self.path / 'bin'
        self.lock = json.loads((ROOT / 'versions.lock.json').read_text())
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('AIRFLOW_', 'MINIO_', 'MLFLOW_', 'SPARK_', 'TRINO_',
                        'PINOT_', 'SUPERSET_', 'OPENMETADATA_', 'OPENSEARCH_', 'JUPYTERHUB_',
                        'REGISTRY_', 'ALIAS_', 'KUBE', 'HELM_', 'K3S_', 'INSTALL_K3S_', 'DOCKER_'))}
        self.env.update(ALIAS_ENV_FILE=str(self.path / 'test.env'),
                        KUBECONFIG=str(self.path / 'kubeconfig'),
                        HELM_CONFIG_HOME=str(self.path / 'helm/config'),
                        HELM_CACHE_HOME=str(STATE / 'cache/helm'),
                        HELM_DATA_HOME=str(self.path / 'helm/data'),
                        HELM_TIMEOUT=str(args.timeout) + 's')
        self.values = {}
        self.hidden = set()
        self.releases = {}
        self.rows = []
        self.current = 'preflight'
        self.created = False
        self.k3s = '/usr/local/bin/k3s'
        self.namespaces = set()
        self.builder_started = False
        self.py = sys.executable
        self.helm = None
        self.port = None
        self.registry_port = None
        self.previous_map_count = None
        self.model = 'alias_smoke_model'
        self.start = time.monotonic()

    def protect(self, value):
        self.hidden.add(value)
        self.hidden.add(base64.b64encode(value.encode()).decode())
        return value

    def token(self):
        return self.protect(secrets.token_hex(24))

    def clean(self, value):
        for secret in sorted(self.hidden, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)(K3S_TOKEN=)\S+', r'\1[REDACTED]', value)
        value = re.sub(r'K10[0-9a-f]{64}::(?:server|agent):[^\s\'"]+', '[REDACTED]', value)
        return value

    def command(self, args, *, data=None, check=True, timeout=None, sensitive=False, binary=False):
        # No shell interpolation; credentials and executable probe bodies use stdin.
        log = self.path / 'logs' / (self.current + '.log')
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            result = subprocess.run([str(a) for a in args], input=data, text=not binary,
                                    capture_output=True, env=self.env,
                                    timeout=timeout or self.args.timeout)
        except subprocess.TimeoutExpired as error:
            parts = [part.decode(errors='replace') if isinstance(part, bytes) else (part or '')
                     for part in (error.stdout, error.stderr)]
            with log.open('a') as stream:
                stream.write('[sensitive output omitted]\n' if sensitive else self.clean(''.join(parts)))
            log.chmod(0o600)
            raise RuntimeError('Timed out running ' + str(args[0]) + '; partial output in logs/' + self.current + '.log') from error
        if binary:
            result.stdout = result.stdout.decode(errors='replace')
            result.stderr = result.stderr.decode(errors='replace')
        with log.open('a') as stream:
            stream.write('[sensitive output omitted]\n' if sensitive else self.clean(result.stdout + result.stderr))
        log.chmod(0o600)
        if check and result.returncode:
            raise RuntimeError(self.clean(result.stderr.strip() or result.stdout.strip())[-3000:]
                               or f'{args[0]} exited {result.returncode}')
        return result.stdout

    def k(self, *args, **kwargs):
        return self.command([self.k3s, 'kubectl', '--kubeconfig', self.env['KUBECONFIG'],
                             '--request-timeout=30s', *args], **kwargs)

    def root_command(self, args, **kwargs):
        return self.command(([] if os.geteuid() == 0 else ['sudo', '-n']) + args, **kwargs)

    def apply(self, *documents):
        self.k('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}))

    def namespace(self, name):
        # Component scripts also use client-side apply for this Namespace. Keep
        # ownership out of last-applied so a later manifest cannot prune it.
        self.apply({'apiVersion': 'v1', 'kind': 'Namespace',
                    'metadata': {'name': name}})
        self.k('label', 'namespace', name, LABEL + '=' + self.id, '--overwrite')
        self.namespaces.add(name)

    def secret(self, namespace, name, values):
        self.apply({'apiVersion': 'v1', 'kind': 'Secret',
                    'metadata': {'name': name, 'namespace': namespace}, 'stringData': values})

    def configmap(self, namespace, name, values):
        self.apply({'apiVersion': 'v1', 'kind': 'ConfigMap',
                    'metadata': {'name': name, 'namespace': namespace}, 'data': values})

    def save_env(self):
        for attribute in ('pg_password', 'mysql_password', 'airflow_password', 'hub_token', 'rancher_password'):
            if hasattr(self, attribute):
                self.values['SMOKE_' + attribute.upper()] = getattr(self, attribute)
        self.env.update(self.values)
        private(self.path / 'test.env', '\n'.join(f'{k}={shlex.quote(v)}' for k, v in self.values.items()) + '\n')

    def preflight(self):
        if getattr(self.args, 'resume_run', None):
            previous = json.loads((self.path / 'report.json').read_text())
            if not previous.get('cluster', {}).get('installer_verified'):
                raise Blocked('Only a run with a verified article installer can be resumed.')
            for key, file in [('installer_sha256', 'install-k3s.sh'), ('article_config_sha256', 'k3s-config.yaml')]:
                if previous['cluster'][key] != hashlib.sha256((ROOT / file).read_bytes()).hexdigest():
                    raise Blocked('The article installer/configuration changed; use a fresh installation test.')
            marker = json.loads(self.k('get', 'namespace', 'alias-smoke-control', '-o', 'json'))
            if marker.get('metadata', {}).get('labels', {}).get(LABEL) != self.id:
                raise Blocked('Cluster ownership label does not match the resumed run.')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            private(self.path / 'attempts' / (stamp + '.json'), json.dumps(previous, indent=2))
            self.previous_run = previous
            self.machine = previous.get('machine', {})
            self.rows.extend(row for row in previous['checks'] if row['component'] == 'install-k3s' and row['status'] == 'PASS')
            return
        if platform.system() != 'Linux' or platform.machine() != 'x86_64':
            raise Blocked('This repository image baseline requires Linux/WSL2 amd64.')
        for tool in ('curl', 'git', 'openssl', 'keytool', 'systemctl'):
            if not shutil.which(tool):
                raise Blocked('Required command not found: ' + tool)
        if shutil.which('k3s') or Path('/etc/rancher/k3s').exists() or Path('/etc/systemd/system/k3s.service').exists():
            raise Blocked('An existing K3s installation was detected. Use a clean test host/VM to validate the article installer without modifying that installation.')
        try:
            self.root_command(['true'], timeout=20)
        except RuntimeError as error:
            raise Blocked('Native install-k3s.sh needs administrator access. Run sudo bash install-k3s.sh --smoke in your terminal. ' + str(error)) from error
        state = self.command(['systemctl', 'is-system-running'], check=False, timeout=20).strip()
        if state not in ('running', 'degraded'):
            raise Blocked('A running systemd host is required for this installation test. In WSL enable systemd and restart the distribution.')
        available = next((int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                          if line.startswith('MemAvailable:')), 0)
        if available < 8 * 1024 * 1024:
            raise Blocked('At least 8 GiB available RAM is required; the complete sequence needs about 12 GiB available.')
        self.machine = {'cpus': os.cpu_count(), 'available_memory_kib': available,
                        'architecture': platform.machine()}

    def tools(self):
        self.bin.mkdir(parents=True, exist_ok=True, mode=0o700)
        version = self.lock['helm']
        explicit = os.environ.get('ALIAS_HELM')
        candidate = explicit or shutil.which('helm')
        if candidate and not self.command([candidate, 'version', '--short']).startswith(version + '+'):
            if explicit:
                raise Blocked('ALIAS_HELM must match ' + version + '; unset it to download the locked client.')
            candidate = None
        if candidate:
            self.helm = candidate
            executable = shutil.which(candidate) or str(Path(candidate).resolve())
            private(self.bin / 'helm', '#!/usr/bin/env bash\nexec ' + shlex.quote(executable) + ' "$@"\n')
            (self.bin / 'helm').chmod(0o700)
        else:
            arch = 'amd64' if platform.machine() == 'x86_64' else 'arm64'
            archive = STATE / 'cache' / f'helm-{version}-linux-{arch}.tar.gz'
            url = 'https://get.helm.sh/' + archive.name
            with urllib.request.urlopen(url + '.sha256sum', timeout=60) as response:
                digest = response.read().decode().split()[0]
            if not re.fullmatch('[0-9a-f]{64}', digest):
                raise RuntimeError('Invalid official Helm checksum')
            download(url, archive, digest)
            with tarfile.open(archive) as bundle:
                private(self.bin / 'helm', '')
                (self.bin / 'helm').write_bytes(bundle.extractfile('linux-' + arch + '/helm').read())
            (self.bin / 'helm').chmod(0o700)
            self.helm = str(self.bin / 'helm')
        try:
            self.command([self.py, '-c', 'import yaml, bcrypt; assert yaml.__version__ == "6.0.3"; assert bcrypt.__version__ == "4.3.0"'])
        except RuntimeError:
            venv = STATE / 'venv'
            self.command([sys.executable, '-m', 'venv', str(venv)])
            self.py = str(venv / 'bin/python')
            self.command([self.py, '-m', 'pip', 'install', '-r', str(ROOT / 'scripts/requirements.txt')], timeout=600)
        # Helm post-renderers and component shell entrypoints use /usr/bin/env python3.
        self.env['PATH'] = str(Path(self.py).parent) + ':' + self.env.get('PATH', '')
        private(self.bin / 'python3', '#!/usr/bin/env bash\nexec ' + shlex.quote(self.py) + ' "$@"\n')
        (self.bin / 'python3').chmod(0o700)

    def copy_sources(self):
        # Copy only versioned sources, never the adopter's .env or generated keys.
        files = self.command(['git', '-C', str(ROOT), 'ls-files', '-z']).split('\0')
        for name in filter(None, files):
            source = ROOT / name
            if source.is_symlink():
                raise RuntimeError('Symlink in source snapshot: ' + name)
            if source.is_file():
                target = self.project / name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copy2(source, target)

    def snapshot(self):
        self.copy_sources()
        self.values.update(REGISTRY_USER='smoke-publisher', REGISTRY_PASSWORD=self.token(),
            JUPYTERHUB_CRYPT_KEY=self.protect(secrets.token_hex(32)), JUPYTERHUB_AUTH_PASSWORD=self.token(),
            TRINO_USER='smoke', TRINO_PASSWORD=self.token(), TRINO_SHARED_SECRET=self.token(),
            TRINO_ALLOWED_NAMESPACES='superset', PINOT_ALLOWED_NAMESPACES='trino',
            OPENSEARCH_ADMIN_USER='search-smoke', OPENSEARCH_ADMIN_PASSWORD=self.token(),
            OPENSEARCH_TRUSTSTORE_PASSWORD=self.token(), OPENSEARCH_APP_USER='catalog-smoke',
            OPENSEARCH_APP_PASSWORD=self.token(), OPENSEARCH_APP_INDEX_PATTERNS='*',
            MINIO_ROOT_USER=self.token(), MINIO_ROOT_PASSWORD=self.token(), MINIO_STORAGE_CLASS='local-path',
            MINIO_STORAGE_SIZE='2Gi', MINIO_CLIENTS='mlflow,spark', MINIO_ALLOWED_NAMESPACES='mlflow,spark',
            MINIO_MLFLOW_BUCKETS='mlflow', MINIO_MLFLOW_ACCESS_KEY=self.token(), MINIO_MLFLOW_SECRET_KEY=self.token(),
            MINIO_SPARK_BUCKETS='spark', MINIO_SPARK_ACCESS_KEY=self.token(), MINIO_SPARK_SECRET_KEY=self.token(),
            MLFLOW_DB_HOST='mysql.databases.svc.cluster.local', MLFLOW_DB_NAME='mlflow', MLFLOW_DB_USER='mlflow',
            MLFLOW_DB_PASSWORD=self.token(), MLFLOW_S3_BUCKET='mlflow',
            MLFLOW_S3_ENDPOINT_URL='http://minio.minio.svc.cluster.local:9000',
            AIRFLOW_FERNET_KEY=self.protect(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()),
            AIRFLOW_WEBSERVER_SECRET_KEY=self.token(), SUPERSET_SECRET_KEY=self.token(),
            SUPERSET_DB_HOST='postgres.databases.svc.cluster.local', SUPERSET_DB_NAME='superset',
            SUPERSET_DB_USER='superset', SUPERSET_DB_PASSWORD=self.token(), SUPERSET_REDIS_PASSWORD=self.token(),
            OPENMETADATA_DB_HOST='postgres.databases.svc.cluster.local', OPENMETADATA_DB_NAME='openmetadata',
            OPENMETADATA_DB_USER='openmetadata', OPENMETADATA_DB_PASSWORD=self.token(),
            OPENMETADATA_DB_PARAMS='sslmode=disable', OPENMETADATA_DB_PORT='5432',
            OPENMETADATA_FERNET_KEY=self.protect(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()),
            OPENMETADATA_PUBLIC_URL='http://openmetadata.openmetadata.svc.cluster.local:8585',
            OPENMETADATA_ADMIN_PRINCIPAL='smoke', OPENMETADATA_PRINCIPAL_DOMAIN='local.test',
            OPENMETADATA_OIDC_AUTHORITY='http://unused.local.test',
            OPENMETADATA_OIDC_DISCOVERY_URL='http://unused.local.test/.well-known/openid-configuration',
            OPENMETADATA_OIDC_JWKS_URL='http://unused.local.test/jwks',
            OPENMETADATA_OIDC_CLIENT_ID='local-smoke', OPENMETADATA_OIDC_CLIENT_SECRET=self.token(),
            OPENMETADATA_SEARCH_HOST='opensearch.opensearch.svc.cluster.local',
            OPENMETADATA_SEARCH_USER='catalog-smoke',
            OPENMETADATA_JWT_PRIVATE_KEY_FILE='openmetadata/runtime-creds/private_key.der',
            OPENMETADATA_JWT_PUBLIC_KEY_FILE='openmetadata/runtime-creds/public_key.der')
        self.pg_password = self.token()
        self.mysql_password = self.token()
        self.airflow_password = self.token()
        self.hub_token = self.token()
        self.rancher_password = self.token()
        self.values.update(MLFLOW_S3_ACCESS_KEY_ID=self.values['MINIO_MLFLOW_ACCESS_KEY'],
                           MLFLOW_S3_SECRET_ACCESS_KEY=self.values['MINIO_MLFLOW_SECRET_KEY'],
                           AIRFLOW_DATABASE_URL='postgresql://airflow:' + self.airflow_password + '@postgres.databases.svc.cluster.local/airflow',
                           OPENMETADATA_SEARCH_PASSWORD=self.values['OPENSEARCH_APP_PASSWORD'])
        self.protect(self.values['AIRFLOW_DATABASE_URL'])
        self.save_env()

    def bootstrap(self):
        if getattr(self.args, 'resume_run', None):
            return self.resume_bootstrap()
        self.tools()
        self.snapshot()
        registries = {'mirrors': {'local-registry:5000': {'endpoint': ['http://127.0.0.1:30500']}},
                      'configs': {host: {'auth': {'username': self.values['REGISTRY_USER'],
                                                'password': self.values['REGISTRY_PASSWORD']}}
                                  for host in ('local-registry:5000', '127.0.0.1:30500')}}
        private(self.path / 'registries.yaml', json.dumps(registries))
        # Inherit the article configuration; add only the test registry and node ownership label.
        code = 'import sys,yaml,json; print(json.dumps(yaml.safe_load(open(sys.argv[1])) or {}))'
        config = json.loads(self.command([self.py, '-c', code, str(ROOT / 'k3s-config.yaml')]))
        config['private-registry'] = str(self.path / 'registries.yaml')
        config.setdefault('node-label', []).append(LABEL + '=' + self.id)
        private(self.path / 'k3s-config.yaml', json.dumps(config, indent=2))
        self.native_config = config
        self.current = 'install-k3s'
        started = time.monotonic()
        # Execute the real article entrypoint, not a K3s container or a second installer.
        self.created = True
        self.root_command(['env', 'ALIAS_ENV_FILE=' + self.env['ALIAS_ENV_FILE'],
            'K3S_VERSION=' + self.lock['k3s'], 'K3S_CONFIG=' + str(self.path / 'k3s-config.yaml'),
            'bash', str(ROOT / 'install-k3s.sh')])
        self.k3s = shutil.which('k3s') or '/usr/local/bin/k3s'
        config = self.root_command(['cat', '/etc/rancher/k3s/k3s.yaml'], sensitive=True)
        private(self.path / 'kubeconfig', config)
        version = self.command([self.k3s, '--version']).splitlines()[0]
        if not re.search(r'(?<!\S)' + re.escape(self.lock['k3s']) + r'(?!\S)', version):
            raise ProbeFailed('The installed K3s version differs from versions.lock.json: ' + version)
        if self.command(['systemctl', 'is-active', 'k3s']).strip() != 'active':
            raise ProbeFailed('The article installer did not start the k3s system service')
        self.until(lambda: json.loads(self.k('get', 'nodes', '-o', 'json')).get('items'), 'K3s node registration')
        self.k('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=' + str(self.args.timeout) + 's')
        self.until(lambda: self.k('-n', 'kube-system', 'get', 'deployment', 'coredns', '-o', 'json'), 'CoreDNS Deployment creation')
        self.k('-n', 'kube-system', 'rollout', 'status', 'deployment/coredns', '--timeout=' + str(self.args.timeout) + 's')
        self.namespace('alias-smoke-control')
        # Exercise the article's non-default NodePort range through the real API.
        self.apply({'apiVersion': 'v1', 'kind': 'Service',
            'metadata': {'name': 'article-nodeport-check', 'namespace': 'alias-smoke-control'},
            'spec': {'type': 'NodePort', 'selector': {'app': 'no-backend-required'},
                     'ports': [{'port': 5000, 'targetPort': 5000, 'nodePort': 10000}]}})
        self.k('-n', 'alias-smoke-control', 'delete', 'service', 'article-nodeport-check')
        private(self.path / 'native.json', json.dumps({'k3s': self.k3s, 'namespaces': sorted(self.namespaces)}))
        self.registry_port = '30500'
        wrapper = ('#!/usr/bin/env bash\nexec ' + shlex.quote(self.k3s) + ' kubectl --kubeconfig '
                   + shlex.quote(self.env['KUBECONFIG']) + ' --request-timeout=30s "$@"\n')
        private(self.bin / 'kubectl', wrapper)
        (self.bin / 'kubectl').chmod(0o700)
        self.env['PATH'] = str(self.bin) + ':' + self.env.get('PATH', '')
        self.record('install-k3s', 'PASS', started,
                    'Native systemd service, locked binary version, Ready node, CoreDNS and article NodePort range verified.')
        self.current = 'bootstrap'

    def resume_bootstrap(self):
        self.tools()
        for line in (self.path / 'test.env').read_text().splitlines():
            key, value = line.split('=', 1)
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise ValueError('Invalid saved test input name')
            words = shlex.split(value)
            self.values[key] = words[0] if words else ''
            if any(part in key for part in ('PASSWORD', 'SECRET', 'TOKEN', 'FERNET', 'CRYPT', 'ACCESS_KEY')):
                if self.values[key]:
                    self.protect(self.values[key])
        self.env.update(self.values)
        self.copy_sources()
        state = json.loads((self.path / 'native.json').read_text())
        self.namespaces = set(state['namespaces'])
        self.created = True
        def existing_secret(namespace, name, key):
            raw = self.k('-n', namespace, 'get', 'secret', name, '--ignore-not-found', '-o', 'json', sensitive=True)
            return base64.b64decode(json.loads(raw)['data'][key]).decode() if raw.strip() else None
        self.pg_password = self.values.get('SMOKE_PG_PASSWORD') or existing_secret('databases', 'postgres', 'POSTGRES_PASSWORD') or self.token()
        self.mysql_password = self.values.get('SMOKE_MYSQL_PASSWORD') or existing_secret('databases', 'mysql', 'MYSQL_ROOT_PASSWORD') or self.token()
        self.airflow_password = urllib.parse.urlsplit(self.values['AIRFLOW_DATABASE_URL']).password
        self.hub_token = self.values.get('SMOKE_HUB_TOKEN') or existing_secret('jupyterhub', 'smoke-api', 'token') or self.token()
        rancher = self.path / 'rancher.local.json'
        self.rancher_password = self.values.get('SMOKE_RANCHER_PASSWORD') or (json.loads(rancher.read_text()).get('bootstrapPassword') if rancher.exists() else None) or self.token()
        for attribute in ('pg_password', 'mysql_password', 'airflow_password', 'hub_token', 'rancher_password'):
            self.protect(getattr(self, attribute))
        self.registry_port = '30500'
        self.env['PATH'] = str(self.bin) + ':' + self.env.get('PATH', '')
        self.save_env()
        print('install-k3s: previous verified installation reused; installer was not reexecuted.', flush=True)

    def until(self, callback, label):
        deadline = time.monotonic() + self.args.timeout
        last = ''
        while time.monotonic() < deadline:
            try:
                result = callback()
                if result:
                    return result
            except (Blocked, ProbeFailed):
                raise
            except (RuntimeError, urllib.error.URLError, KeyError, ValueError) as error:
                last = str(error)
            time.sleep(2)
        raise RuntimeError('Timed out waiting for ' + label + ': ' + last[-1000:])

    def chart(self, name):
        chart = self.lock['charts'][name]
        archive = STATE / 'cache/charts' / (name + '-' + chart['version'] + '.tgz')
        download(urllib.parse.urljoin(chart['index'], chart['urls'][0]), archive, chart['digest'])
        if name in ('trino', 'openmetadata'):
            patched = self.path / (name + '-patched.tgz')
            self.command([self.py, str(self.project / 'scripts' / ('prepare-' + name + '-chart.py')), str(archive), str(patched)])
            return patched
        return archive

    def deploy(self, name, overrides=None, runtime=True, namespace=None, release=None):
        namespace = namespace or name
        release = release or name
        self.namespace(namespace)
        archive = self.project / 'minio/chart' if name == 'minio' else self.chart(name)
        command = [self.helm, 'upgrade', '--install', release, str(archive), '--namespace', namespace,
                   '--wait', '--wait-for-jobs', '--timeout', str(self.args.timeout) + 's', '--history-max', '2']
        baseline = self.project / name / 'values.yaml'
        if baseline.exists():
            command += ['--values', str(baseline)]
        if runtime:
            output = self.path / (name + '.runtime.json')
            self.command([self.py, str(self.project / 'scripts/runtime-secrets.py'), name, str(output)])
            command += ['--values', str(output)]
        if overrides:
            output = self.path / (name + '.local.json')
            private(output, json.dumps(overrides))
            command += ['--values', str(output)]
        pinned = self.project / 'versions' / (name + '.values.json')
        if pinned.exists():
            command += ['--values', str(pinned)]
        command += ['--post-renderer', str(self.project / 'scripts/locked-images.py')]
        # Record before installing: failures must also release partially started workloads.
        self.releases[name] = (release, namespace)
        self.command(command)

    def pod(self, namespace, selector):
        data = json.loads(self.k('-n', namespace, 'get', 'pods', '-l', selector, '-o', 'json'))
        candidates = [item for item in data['items'] if item['status'].get('phase') == 'Running'
                      and not item['metadata'].get('deletionTimestamp')]
        if not candidates:
            raise RuntimeError('No running Pod for ' + namespace + '/' + selector)
        return candidates[0]['metadata']['name']

    def execute(self, namespace, pod, body, payload=None, python='python', container=None):
        source = 'SMOKE = ' + repr(payload or {}) + '\n' + body
        args = ['-n', namespace, 'exec', '-i', pod]
        if container:
            args += ['-c', container]
        return self.k(*args, '--', python, '-', data=source)

    def probe(self, name, namespace, selector, payload=None, python='python', container=None):
        directory = ROOT / 'scripts/smoke-probes'
        body = (directory / 'common.py').read_text() + '\n' + (directory / (name + '.py')).read_text()
        return self.execute(namespace, self.pod(namespace, selector), body, payload, python, container)

    def workload(self, namespace, name, image, command, env=None, volumes=None, mounts=None, kind='Deployment'):
        container = {'name': name, 'image': image, 'command': command,
                     'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                   'limits': {'cpu': '1', 'memory': '1Gi'}}}
        if env:
            container['env'] = env
        if mounts:
            container['volumeMounts'] = mounts
        spec = {'containers': [container], 'restartPolicy': 'Never' if kind == 'Job' else 'Always'}
        if volumes:
            spec['volumes'] = volumes
        document = {'apiVersion': 'batch/v1' if kind == 'Job' else 'apps/v1', 'kind': kind,
            'metadata': {'name': name, 'namespace': namespace},
            'spec': {'template': {'metadata': {'labels': {'app': name}}, 'spec': spec}}}
        if kind == 'Deployment':
            document['spec'].update(selector={'matchLabels': {'app': name}}, replicas=1)
        else:
            document['spec'].update(backoffLimit=0, activeDeadlineSeconds=self.args.timeout)
        if kind == 'Job':
            self.k('-n', namespace, 'delete', 'job', name, '--ignore-not-found', '--wait=true')
        self.apply(document)
        if kind == 'Deployment':
            self.k('-n', namespace, 'rollout', 'status', 'deployment/' + name, '--timeout=' + str(self.args.timeout) + 's')
        else:
            def complete():
                status = json.loads(self.k('-n', namespace, 'get', 'job', name, '-o', 'json')).get('status', {})
                if status.get('failed'):
                    raise ProbeFailed('Job failed: ' + namespace + '/' + name)
                return bool(status.get('succeeded'))
            self.until(complete, namespace + '/' + name)

    def pvc(self, namespace, name, size='1Gi'):
        self.apply({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
            'metadata': {'name': name, 'namespace': namespace},
            'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'local-path',
                     'resources': {'requests': {'storage': size}}}})

    def service(self, namespace, name, port):
        self.apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': namespace},
            'spec': {'selector': {'app': name}, 'ports': [{'port': port, 'targetPort': port}]}})

    def storage(self):
        self.namespace('smoke-storage')
        self.pvc('smoke-storage', 'roundtrip')
        for name, command in [('writer', 'printf alias-smoke > /data/probe'),
                              ('reader', 'test "$(cat /data/probe)" = alias-smoke')]:
            self.workload('smoke-storage', name, self.lock['images']['busybox:1.38.0'], ['sh', '-ec', command],
                volumes=[{'name': 'data', 'persistentVolumeClaim': {'claimName': 'roundtrip'}}],
                mounts=[{'name': 'data', 'mountPath': '/data'}], kind='Job')

    def databases(self):
        self.namespace('databases')
        self.secret('databases', 'postgres', {'POSTGRES_PASSWORD': self.pg_password})
        sql = '\n'.join("CREATE USER %s WITH PASSWORD '%s'; CREATE DATABASE %s OWNER %s;" % (name, password, name, name)
            for name, password in [('airflow', self.airflow_password), ('superset', self.values['SUPERSET_DB_PASSWORD']),
                                   ('openmetadata', self.values['OPENMETADATA_DB_PASSWORD'])])
        self.secret('databases', 'postgres-init', {'init.sql': sql})
        for name in ('postgres', 'mysql84-data'):
            self.pvc('databases', name, '2Gi')
        self.service('databases', 'postgres', 5432)
        self.workload('databases', 'postgres', self.lock['images']['postgres:14'], ['docker-entrypoint.sh', 'postgres'],
            env=[{'name': 'POSTGRES_PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'postgres', 'key': 'POSTGRES_PASSWORD'}}},
                 {'name': 'PGDATA', 'value': '/var/lib/postgresql/data/pgdata'}],
            volumes=[{'name': 'data', 'persistentVolumeClaim': {'claimName': 'postgres'}},
                     {'name': 'init', 'secret': {'secretName': 'postgres-init'}}],
            mounts=[{'name': 'data', 'mountPath': '/var/lib/postgresql/data'},
                    {'name': 'init', 'mountPath': '/docker-entrypoint-initdb.d'}])
        self.until(lambda: self.k('-n', 'databases', 'exec', 'deployment/postgres', '--', 'pg_isready', '-U', 'postgres'), 'PostgreSQL')
        self.secret('databases', 'mysql', {'MYSQL_ROOT_PASSWORD': self.mysql_password,
                    'MYSQL_DATABASE': 'mlflow', 'MYSQL_USER': 'mlflow', 'MYSQL_PASSWORD': self.values['MLFLOW_DB_PASSWORD']})
        self.service('databases', 'mysql', 3306)
        # Exercise the committed server definition, with only local identity,
        # test credentials and dynamic PVC substitutions. Keep its image, args,
        # probes and update strategy so the test cannot drift from the example.
        code = ('import sys,json,yaml; print(json.dumps(next(x for x in '
                'yaml.safe_load_all(open(sys.argv[1])) if x and x["kind"]=="Deployment")))')
        database = json.loads(self.command([self.py, '-c', code,
                              str(self.project / 'databases/mlflow-db/deploy.yaml')]))
        database['metadata']['name'] = 'mysql'
        database['spec']['selector']['matchLabels'] = {'app': 'mysql'}
        template = database['spec']['template']
        template['metadata']['labels']['app'] = 'mysql'
        container = template['spec']['containers'][0]
        if container['image'] != self.lock['images']['mysql:8.4.7']:
            raise ProbeFailed('The committed MySQL server does not match the 8.4.7 image lock')
        env = container['env']
        for item in env:
            item['valueFrom']['secretKeyRef']['name'] = 'mysql'
        for volume in template['spec']['volumes']:
            volume['persistentVolumeClaim']['claimName'] = 'mysql84-data'
        self.apply(database)
        self.k('-n', 'databases', 'rollout', 'status', 'deployment/mysql', '--timeout=' + str(self.args.timeout) + 's')
        query = 'CREATE TEMPORARY TABLE alias_smoke (id INT); INSERT INTO alias_smoke VALUES (42); SELECT id FROM alias_smoke; DROP TABLE alias_smoke;'
        pg = self.k('-n', 'databases', 'exec', '-i', 'deployment/postgres', '--', 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-At', data=query)
        if '42' not in pg.splitlines():
            raise RuntimeError('PostgreSQL round trip returned no row')
        def mysql():
            result = self.k('-n', 'databases', 'exec', '-i', 'deployment/mysql', '--', 'sh', '-ec',
                'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -N', data=query)
            if result.strip() != '42':
                raise RuntimeError('MySQL round trip returned no row')
            return True
        self.until(mysql, 'MySQL round trip')
        version = self.k('-n', 'databases', 'exec', '-i', 'deployment/mysql', '--', 'sh', '-ec',
            'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -N', data='SELECT VERSION();')
        if version.strip() != '8.4.7':
            raise ProbeFailed('Unexpected running MySQL version: ' + version.strip())
        window = self.k('-n', 'databases', 'exec', '-i', 'deployment/mysql', '--', 'sh', '-ec',
            'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -N',
            data='SELECT ROW_NUMBER() OVER (ORDER BY id) FROM (SELECT 1 AS id) AS synthetic;')
        if window.strip() != '1':
            raise ProbeFailed('MySQL does not support the window functions required by MLflow model queries')
        trigger = self.k('-n', 'databases', 'exec', '-i', 'deployment/mysql', '--', 'sh', '-ec',
            'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE" -N',
            data='DROP TABLE IF EXISTS alias_smoke_trigger_probe; CREATE TABLE alias_smoke_trigger_probe (id INT); '
                 'CREATE TRIGGER alias_smoke_before_insert BEFORE INSERT ON alias_smoke_trigger_probe '
                 'FOR EACH ROW SET NEW.id=42; INSERT INTO alias_smoke_trigger_probe VALUES(0); '
                 'SELECT id FROM alias_smoke_trigger_probe; DROP TABLE alias_smoke_trigger_probe;')
        if trigger.strip() != '42':
            raise ProbeFailed('The application database account cannot create the triggers required by MLflow migrations')
        # Check service DNS and Pod-to-Pod networking, not only local database sockets.
        self.workload('databases', 'postgres-service-client', self.lock['images']['postgres:14'],
            ['sh', '-ec', 'export PGPASSWORD="$POSTGRES_PASSWORD"; test "$(psql -h postgres.databases.svc.cluster.local -U postgres -At -v ON_ERROR_STOP=1 -c "SELECT 42")" = 42'],
            env=[{'name': 'POSTGRES_PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'postgres', 'key': 'POSTGRES_PASSWORD'}}}], kind='Job')
        self.workload('databases', 'mysql-service-client', self.lock['images']['mysql:8.4.7'],
            ['sh', '-ec', 'export MYSQL_PWD="$MYSQL_PASSWORD"; test "$(mysql -h mysql.databases.svc.cluster.local -u "$MYSQL_USER" "$MYSQL_DATABASE" -N -e "SELECT 42")" = 42'],
            env=env, kind='Job')

    def registry(self):
        self.namespace('docker-registry')
        self.pvc('docker-registry', 'docker-registry-pv-claim', '5Gi')
        # bcrypt is already a locked deployment-tool dependency; no host Docker is needed.
        code = ('import os,bcrypt; print(os.environ["REGISTRY_USER"]+":"+'
                'bcrypt.hashpw(os.environ["REGISTRY_PASSWORD"].encode(),bcrypt.gensalt(12)).decode())')
        private(self.project / 'registry/registry-creds/htpasswd', self.command([self.py, '-c', code]))
        htpasswd = (self.project / 'registry/registry-creds/htpasswd').read_text()
        self.deploy('registry', {'service': {'type': 'NodePort', 'nodePort': 30500},
                               'secrets': {'htpasswd': htpasswd}}, runtime=False,
                    namespace='docker-registry', release='docker-registry')
        context = self.path / 'registry-probe'
        private(context / 'Dockerfile', 'FROM ' + self.lock['images']['busybox:1.38.0'] + '\n')
        image = self.build_image('probe', context)
        self.workload('docker-registry', 'registry-consumer', image, ['sh', '-ec', 'test 42 -eq 42'], kind='Job')

    def image_digest(self, repository, tag):
        url = 'http://127.0.0.1:' + self.registry_port + '/v2/' + repository + '/manifests/' + tag
        auth = base64.b64encode((self.values['REGISTRY_USER'] + ':' + self.values['REGISTRY_PASSWORD']).encode()).decode()
        req = urllib.request.Request(url, headers={'Authorization': 'Basic ' + auth,
            'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            digest = 'sha256:' + hashlib.sha256(data).hexdigest()
            if response.headers['Docker-Content-Digest'] != digest:
                raise RuntimeError('Registry manifest digest mismatch')
        return 'local-registry:5000/' + repository + '@' + digest

    def build_image(self, name, directory):
        self.start_builder()
        pod = self.pod('docker-registry', 'app=smoke-buildkit')
        target = '/tmp/alias-context-' + name
        self.k('-n', 'docker-registry', 'exec', pod, '--', 'mkdir', '-p', target)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
            bundle.add(self.project / directory, arcname='.')
        self.k('-n', 'docker-registry', 'exec', '-i', pod, '--', 'tar', '-xzf', '-', '-C', target,
               data=archive.getvalue(), binary=True)
        tag = 'docker-registry.docker-registry.svc.cluster.local:5000/' + name + ':local'
        self.k('-n', 'docker-registry', 'exec', pod, '--', 'buildctl', 'build',
               '--frontend', 'dockerfile.v0', '--local', 'context=' + target, '--local', 'dockerfile=' + target,
               '--output', 'type=image,name=' + tag + ',push=true,registry.insecure=true',
               timeout=self.args.build_timeout)
        return self.image_digest(name, 'local')

    def start_builder(self):
        if self.builder_started:
            return
        auth = base64.b64encode((self.values['REGISTRY_USER'] + ':' + self.values['REGISTRY_PASSWORD']).encode()).decode()
        config = json.dumps({'auths': {'docker-registry.docker-registry.svc.cluster.local:5000': {'auth': auth}}})
        self.secret('docker-registry', 'buildkit-auth', {'config.json': config})
        self.apply({'apiVersion': 'apps/v1', 'kind': 'Deployment',
            'metadata': {'name': 'smoke-buildkit', 'namespace': 'docker-registry'},
            'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'smoke-buildkit'}},
                'template': {'metadata': {'labels': {'app': 'smoke-buildkit'}},
                    'spec': {'automountServiceAccountToken': False, 'containers': [{
                        'name': 'buildkit', 'image': self.lock['images']['moby/buildkit:v0.20.2'],
                        'securityContext': {'privileged': True},
                        'readinessProbe': {'exec': {'command': ['buildctl', 'debug', 'workers']}, 'periodSeconds': 5},
                        'resources': {'requests': {'cpu': '500m', 'memory': '1Gi'},
                                      'limits': {'cpu': '3', 'memory': '4Gi'}},
                        'volumeMounts': [{'name': 'auth', 'mountPath': '/root/.docker', 'readOnly': True},
                                         {'name': 'cache', 'mountPath': '/var/lib/buildkit'}]}],
                        'volumes': [{'name': 'auth', 'secret': {'secretName': 'buildkit-auth'}},
                                    {'name': 'cache', 'emptyDir': {}}]}}}})
        self.k('-n', 'docker-registry', 'rollout', 'status', 'deployment/smoke-buildkit',
               '--timeout=' + str(self.args.timeout) + 's')
        self.builder_started = True

    def minio(self):
        self.values['MINIO_IMAGE'] = self.values.get('MINIO_IMAGE') or self.build_image('minio', 'minio')
        self.save_env()
        self.deploy('minio')
        self.probe('minio', 'minio', 'app.kubernetes.io/name=alias-minio', {
            'access': self.values['MINIO_MLFLOW_ACCESS_KEY'], 'secret': self.values['MINIO_MLFLOW_SECRET_KEY']})

    def mlflow(self):
        self.deploy('mlflow', {'extraEnvVars': {'MLFLOW_SERVER_ALLOWED_HOSTS':
            'localhost:*,127.0.0.1:*,mlflow.mlflow.svc.cluster.local:5000'}})
        self.probe('mlflow', 'mlflow', 'app.kubernetes.io/instance=mlflow', {'model': self.model})

    def spark(self):
        self.values.update(SPARK_IMAGE=self.values.get('SPARK_IMAGE') or self.build_image('spark-s3', 'docker-images/pyspark-aws-psql'),
            SPARK_S3_ENABLED='true', SPARK_S3_ENDPOINT_URL='http://minio.minio.svc.cluster.local:9000',
            SPARK_S3_BUCKET='spark', SPARK_S3_ACCESS_KEY_ID=self.values['MINIO_SPARK_ACCESS_KEY'],
            SPARK_S3_SECRET_ACCESS_KEY=self.values['MINIO_SPARK_SECRET_KEY'])
        self.save_env()
        self.namespace('spark')
        self.namespace('spark-operator')
        archive = self.chart('spark-operator')
        self.env['SPARK_OPERATOR_CHART'] = str(archive)
        self.releases['spark'] = ('spark-operator', 'spark-operator')
        self.command(['bash', str(self.project / 'spark-operator/deploy.sh')])
        self.k('-n', 'spark', 'delete', 'sparkapplication', 'alias-spark-smoke', '--ignore-not-found')
        self.command(['bash', str(self.project / 'spark/submit.sh')])
        def complete():
            state = json.loads(self.k('-n', 'spark', 'get', 'sparkapplication', 'alias-spark-smoke', '-o', 'json'))
            state = state.get('status', {}).get('applicationState', {}).get('state')
            if state in ('FAILED', 'SUBMISSION_FAILED', 'FAILING'):
                raise ProbeFailed('Spark application failed; inspect spark diagnostics.')
            return state == 'COMPLETED'
        self.until(complete, 'distributed Spark S3 job')
        self.spark_template = json.loads(self.command(['bash', str(self.project / 'spark/submit.sh'), '--render']))

    def spark_binding(self, namespace, account):
        self.namespace(namespace)
        self.apply({'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': account, 'namespace': namespace}},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role',
             'metadata': {'name': 'smoke-submitter', 'namespace': 'spark'},
             'rules': [{'apiGroups': ['sparkoperator.k8s.io'], 'resources': ['sparkapplications'],
                        'verbs': ['get', 'create', 'delete']}]},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
             'metadata': {'name': 'smoke-' + namespace, 'namespace': 'spark'},
             'subjects': [{'kind': 'ServiceAccount', 'name': account, 'namespace': namespace}],
             'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'smoke-submitter'}})

    def airflow(self):
        self.spark_binding('airflow', 'smoke-airflow')
        template = json.loads(json.dumps(self.spark_template))
        template['metadata']['name'] = 'alias-airflow-smoke'
        launch = (ROOT / 'scripts/smoke-probes/submit-spark.py').read_text()
        dag = ('from datetime import datetime\nfrom airflow import DAG\nfrom airflow.operators.python import PythonOperator\n'
               'def check():\n' + '    SMOKE = ' + repr({'application': template, 'timeout': self.args.timeout}) + '\n'
               + '\n'.join('    ' + line for line in launch.splitlines()) + '\n'
               'with DAG("alias_smoke", start_date=datetime(2024,1,1), schedule=None, catchup=False, is_paused_upon_creation=False) as dag:\n'
               '    PythonOperator(task_id="spark_roundtrip", python_callable=check)\n')
        self.configmap('airflow', 'smoke-dags', {'alias_smoke.py': dag})
        self.deploy('airflow', {'executor': 'LocalExecutor', 'redis': {'enabled': False},
            'workers': {'replicas': 0}, 'triggerer': {'enabled': False}, 'statsd': {'enabled': False},
            'webserver': {'defaultUser': {'enabled': False}, 'service': {'type': 'ClusterIP',
                'ports': [{'name': 'airflow-ui', 'port': 8080, 'targetPort': 8080}]}},
            'scheduler': {'serviceAccount': {'create': False, 'name': 'smoke-airflow'},
                          'resources': {'requests': {'cpu': '250m', 'memory': '512Mi'}}},
            'config': {'core': {'load_examples': 'False', 'parallelism': '2'}},
            'volumes': [{'name': 'smoke-dags', 'configMap': {'name': 'smoke-dags'}}],
            'volumeMounts': [{'name': 'smoke-dags', 'mountPath': '/opt/airflow/dags/alias_smoke.py',
                             'subPath': 'alias_smoke.py', 'readOnly': True}]})
        self.probe('airflow', 'airflow', 'component=scheduler', {'timeout': self.args.timeout}, container='scheduler')

    def jupyterhub(self):
        self.spark_binding('jupyterhub', 'spark')
        self.secret('jupyterhub', 'smoke-api', {'token': self.hub_token})
        self.deploy('jupyterhub', {'hub': {'image': {'pullSecrets': []},
            'extraEnv': {'SMOKE_API_TOKEN': {'valueFrom': {'secretKeyRef': {'name': 'smoke-api', 'key': 'token'}}}},
            'extraConfig': {'smoke-api': 'import os\nc.JupyterHub.services = [{"name":"smoke", "api_token":os.environ["SMOKE_API_TOKEN"]}]\nc.JupyterHub.load_roles = [{"name":"smoke-admin", "scopes":["admin:users", "admin:servers", "access:servers"], "services":["smoke"]}]'}},
            'proxy': {'service': {'type': 'ClusterIP', 'nodePorts': {'http': None}}},
            'singleuser': {'storage': {'type': 'dynamic', 'dynamic': {'storageClass': 'local-path'}},
                           'extraPodConfig': {'automountServiceAccountToken': True},
                           'cpu': {'guarantee': 0.1, 'limit': 1}, 'memory': {'guarantee': '512M', 'limit': '2G'}},
            'scheduling': {'userScheduler': {'enabled': False}},
            'prePuller': {'hook': {'enabled': False}, 'continuous': {'enabled': False}}})
        self.probe('jupyterhub', 'jupyterhub', 'component=hub', {'token': self.hub_token, 'timeout': self.args.timeout})
        template = json.loads(json.dumps(self.spark_template))
        template['metadata']['name'] = 'alias-notebook-smoke'
        self.probe('submit-spark', 'jupyterhub', 'component=singleuser-server',
                   {'application': template, 'timeout': self.args.timeout}, python='python3')

    def opensearch(self):
        count = int(self.root_command(['sysctl', '-n', 'vm.max_map_count']).strip())
        if count < 262144:
            self.previous_map_count = count
            self.root_command(['sysctl', '-w', 'vm.max_map_count=262144'])
        self.command(['bash', str(self.project / 'opensearch/gen-security.sh')])
        self.deploy('opensearch')
        self.namespace('smoke-client')
        self.workload('smoke-client', 'client', self.lock['images']['python:3.11.11-slim-bookworm'], ['sleep', 'infinity'])
        ca = (self.project / 'opensearch/runtime-creds/ca.pem').read_text()
        self.probe('opensearch', 'smoke-client', 'app=client', {'ca': ca, 'user': self.values['OPENSEARCH_ADMIN_USER'],
            'password': self.values['OPENSEARCH_ADMIN_PASSWORD']})

    def openmetadata(self):
        self.command(['bash', str(self.project / 'openmetadata/gen-keys.sh')])
        self.values.update(OPENMETADATA_SEARCH_TRUSTSTORE_FILE=str(self.project / 'opensearch/runtime-creds/truststore.jks'),
                           OPENMETADATA_SEARCH_TRUSTSTORE_PASSWORD=self.values['OPENSEARCH_TRUSTSTORE_PASSWORD'])
        self.save_env()
        url = self.values['OPENMETADATA_PUBLIC_URL']
        self.deploy('openmetadata', {'openmetadata': {'config': {'authentication': {'provider': 'basic',
            'clientType': 'public', 'authority': url, 'publicKeys': [url + '/api/v1/system/config/jwks'],
            'oidcConfiguration': {'enabled': False}}}}})
        key = self.project / 'openmetadata/runtime-creds/private_key.der'
        public = self.project / 'openmetadata/runtime-creds/public_key.der'
        enc = lambda data: base64.urlsafe_b64encode(data).rstrip(b'=')
        header = enc(json.dumps({'alg': 'RS256', 'typ': 'JWT', 'kid': hashlib.sha256(public.read_bytes()).hexdigest()[:32]}).encode())
        claims = enc(json.dumps({'sub': 'smoke', 'email': 'smoke@local.test', 'isBot': False,
            'iss': url, 'iat': int(time.time()), 'exp': int(time.time()) + 3600}).encode())
        message = header + b'.' + claims
        signed = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(key), '-keyform', 'DER'],
                                input=message, capture_output=True, check=True).stdout
        token = self.protect((message + b'.' + enc(signed)).decode())
        self.probe('openmetadata', 'smoke-client', 'app=client', {'token': token, 'model': self.model, 'timeout': self.args.timeout})

    def pinot(self):
        self.deploy('pinot', {'minionStateless': {'enabled': False}})
        self.namespace('pinot')
        self.workload('pinot', 'client', self.lock['images']['python:3.11.11-slim-bookworm'], ['sleep', 'infinity'])
        self.probe('pinot', 'pinot', 'app=client', {'timeout': self.args.timeout})

    def trino(self):
        catalogs = {'tpch': 'connector.name=tpch\n', 'pinot':
            'connector.name=pinot\npinot.controller-urls=http://pinot-controller.pinot.svc.cluster.local:9000\n'
            'pinot.broker-url=pinot-broker.pinot.svc.cluster.local:8099\npinot.prefer-broker-queries=true\npinot.forbid-segment-queries=true\n'}
        private(self.path / 'catalogs.json', json.dumps(catalogs))
        self.values['TRINO_CATALOGS_FILE'] = str(self.path / 'catalogs.json')
        self.save_env()
        if getattr(self.args, 'resume_run', None):
            # This generated catalog only names the owned synthetic Pinot/TPCH sources.
            self.k('-n', 'trino', 'delete', 'secret', 'trino-catalogs', '--ignore-not-found')
        self.command(['bash', str(self.project / 'trino/gen-security.sh')])
        small = {'jvm': {'maxHeapSize': '1G'}, 'config': {'query': {'maxMemoryPerNode': '256MB'},
            'memory': {'heapHeadroomPerNode': '256MB'}},
            'resources': {'requests': {'cpu': '250m', 'memory': '1536Mi'}, 'limits': {'cpu': '2', 'memory': '2Gi'}}}
        self.deploy('trino', {'server': {'config': {'query': {'maxMemory': '512MB'}}}, 'coordinator': small, 'worker': small})
        self.namespace('trino')
        self.workload('trino', 'client', self.lock['images']['python:3.11.11-slim-bookworm'], ['sleep', 'infinity'])
        self.probe('trino', 'trino', 'app=client', self.trino_payload())

    def trino_payload(self):
        return {'ca': (self.project / 'trino/runtime-creds/ca.pem').read_text(),
                'user': self.values['TRINO_USER'], 'password': self.values['TRINO_PASSWORD'], 'timeout': self.args.timeout}

    def superset(self):
        self.deploy('superset', {'supersetWorker': {'replicas': {'enabled': True, 'replicaCount': 0}},
            'service': {'type': 'ClusterIP', 'nodePort': {'http': None}},
            'extraEnv': {'SERVER_WORKER_AMOUNT': '1'},
            'resources': {'requests': {'cpu': '250m', 'memory': '512Mi'}, 'limits': {'cpu': '2', 'memory': '2Gi'}},
            'redis': {'master': {'persistence': {'enabled': False}}}})
        self.probe('superset', 'superset', 'app=superset', self.trino_payload())

    def pgadmin(self):
        self.namespace('pgadmin')
        password = self.token()
        self.secret('pgadmin', 'smoke-login', {'password': password})
        servers = {'Servers': {'1': {'Name': 'Local smoke PostgreSQL', 'Group': 'Smoke',
            'Host': self.values['SUPERSET_DB_HOST'], 'Port': 5432, 'MaintenanceDB': 'superset',
            'Username': 'superset', 'SSLMode': 'prefer'}}}
        self.configmap('pgadmin', 'servers', {'servers.json': json.dumps(servers)})
        self.workload('pgadmin', 'pgadmin', self.lock['images']['dpage/pgadmin4:9.3'], ['/entrypoint.sh'],
            env=[{'name': 'PGADMIN_DEFAULT_EMAIL', 'value': 'smoke@example.org'},
                 {'name': 'PGADMIN_DEFAULT_PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'smoke-login', 'key': 'password'}}},
                 {'name': 'PGADMIN_CONFIG_ENHANCED_COOKIE_PROTECTION', 'value': 'False'}],
            volumes=[{'name': 'servers', 'configMap': {'name': 'servers'}}],
            mounts=[{'name': 'servers', 'mountPath': '/pgadmin4/servers.json', 'subPath': 'servers.json'}])
        self.probe('pgadmin', 'pgadmin', 'app=pgadmin', {'password': password,
                   'db_password': self.values['SUPERSET_DB_PASSWORD'], 'timeout': self.args.timeout}, python='/venv/bin/python3')

    def homepage(self):
        self.deploy('homepage', {'service': {'main': {'type': 'ClusterIP', 'ports': {'http': {'nodePort': None}}}},
            'config': {'bookmarks': [], 'widgets': [], 'services': [{'Smoke': [
                {'PostgreSQL': {'href': 'http://postgres.databases.svc.cluster.local:5432', 'description': 'Local smoke database'}},
                {'Registry': {'href': 'http://docker-registry.docker-registry.svc.cluster.local:5000/v2/', 'description': 'Local smoke registry'}}]}]}}, runtime=False)
        self.namespace('homepage')
        self.workload('homepage', 'client', self.lock['images']['python:3.11.11-slim-bookworm'], ['sleep', 'infinity'])
        self.probe('homepage', 'homepage', 'app=client')

    def cert_manager(self):
        self.deploy('cert-manager', {'installCRDs': True}, runtime=False)
        self.apply({'apiVersion': 'cert-manager.io/v1', 'kind': 'Issuer',
            'metadata': {'name': 'smoke', 'namespace': 'cert-manager'}, 'spec': {'selfSigned': {}}},
            {'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate',
             'metadata': {'name': 'smoke', 'namespace': 'cert-manager'},
             'spec': {'secretName': 'smoke-tls', 'dnsNames': ['smoke.local.test'], 'issuerRef': {'name': 'smoke'}}})
        self.k('-n', 'cert-manager', 'wait', '--for=condition=Ready', 'certificate/smoke', '--timeout=' + str(self.args.timeout) + 's')
        cert = json.loads(self.k('-n', 'cert-manager', 'get', 'secret', 'smoke-tls', '-o', 'json', sensitive=True))
        if not all(key in cert['data'] for key in ('tls.crt', 'tls.key')):
            raise RuntimeError('cert-manager returned incomplete certificate Secret')

    def rancher(self):
        self.deploy('rancher', {'hostname': 'rancher.local.test', 'replicas': 1,
                              'bootstrapPassword': self.rancher_password}, runtime=False, namespace='cattle-system')
        self.namespace('cattle-system')
        self.workload('cattle-system', 'client', self.lock['images']['python:3.11.11-slim-bookworm'], ['sleep', 'infinity'])
        certificate = json.loads(self.k('-n', 'cattle-system', 'get', 'secret', 'tls-rancher', '-o', 'json', sensitive=True))
        self.probe('rancher', 'cattle-system', 'app=client', {'password': self.rancher_password,
            'ca': base64.b64decode(certificate['data']['tls.crt']).decode(), 'timeout': self.args.timeout})

    def glusterfs(self):
        raise Blocked('Replicated GlusterFS/NFS-Ganesha needs three prepared storage hosts and mounted bricks. '
                      'The storage stage only verifies this local cluster\'s PVC; replication is not tested.')

    def diagnostics(self):
        if not self.created:
            return
        self.root_command(['journalctl', '-u', 'k3s', '--no-pager', '-n', '150'], check=False)
        for args in [('get', 'pods', '-A', '-o', 'wide'), ('get', 'events', '-A', '--sort-by=.lastTimestamp'),
                     ('get', 'pvc', '-A')]:
            self.k(*args, check=False)
        pods = json.loads(self.k('get', 'pods', '-A', '-o', 'json') or '{"items":[]}')
        for pod in pods['items']:
            self.k('-n', pod['metadata']['namespace'], 'logs', pod['metadata']['name'],
                   '--all-containers', '--tail=80', check=False, timeout=40)

    def release_unused(self, remaining):
        needed = set(selection(','.join(remaining))) if remaining else set()
        for component, (release, namespace) in list(self.releases.items()):
            if component not in needed:
                self.command([self.helm, 'uninstall', release, '-n', namespace,
                              '--ignore-not-found', '--wait', '--timeout', str(self.args.timeout) + 's'])
                del self.releases[component]
        for component, namespaces in [('registry', ['docker-registry']), ('databases', ['databases']), ('opensearch', ['smoke-client']),
            ('pinot', ['pinot']), ('trino', ['trino']), ('pgadmin', ['pgadmin']), ('homepage', ['homepage']),
            ('rancher', ['cattle-system'])]:
            if component not in needed:
                for namespace in namespaces:
                    self.k('-n', namespace, 'delete', 'deployment', '--all', '--ignore-not-found', check=False)

    def cleanup_workloads(self):
        if not self.namespaces:
            return
        marker = json.loads(self.k('get', 'namespace', 'alias-smoke-control', '-o', 'json'))
        if marker.get('metadata', {}).get('labels', {}).get(LABEL) != self.id:
            raise RuntimeError('Cluster ownership label does not match; refusing namespace cleanup')
        for name in sorted(self.namespaces - {'alias-smoke-control'}):
            namespace = self.k('get', 'namespace', name, '--ignore-not-found', '-o', 'json')
            if not namespace.strip():
                continue
            if json.loads(namespace).get('metadata', {}).get('labels', {}).get(LABEL) != self.id:
                raise RuntimeError('Namespace ownership label does not match: ' + name)
            self.k('delete', 'namespace', name, '--wait=false')

    def record(self, name, status, started, detail=''):
        self.rows.append({'component': name, 'status': status,
                          'duration_seconds': round(time.monotonic() - started, 2),
                          'detail': self.clean(detail), 'purpose': PURPOSES.get(name, name),
                          'log': 'logs/' + name + '.log'})
        self.report()
        print(f'{name}: {status}' + (' — ' + self.clean(detail)[:250] if detail else ''), flush=True)

    def report(self):
        report = {'run_id': self.id, 'mode': self.args.mode,
                  'cluster': {'kind': 'native-k3s', 'host': platform.node(),
                              'resumed': bool(getattr(self.args, 'resume_run', None)),
                              'installer': 'install-k3s.sh',
                              'installer_sha256': hashlib.sha256((ROOT / 'install-k3s.sh').read_bytes()).hexdigest(),
                              'article_config_sha256': hashlib.sha256((ROOT / 'k3s-config.yaml').read_bytes()).hexdigest(),
                              'installer_verified': any(row['component'] == 'install-k3s' and row['status'] == 'PASS' for row in self.rows),
                              'installation_attempted': self.created, 'automatically_uninstalled': False},
                  'elapsed_seconds': round(time.monotonic() - self.start, 2),
                  'machine': getattr(self, 'machine', {}), 'versions': {'k3s': self.lock['k3s'], 'helm': self.lock['helm']},
                  'checks': self.rows, 'limitations': [
                      'Native single-node K3s; multi-host GlusterFS replication is not exercised.',
                      'OpenMetadata uses local basic/JWT auth and API-based MLflow import; external OIDC and the ingestion connector are not tested.',
                      'JupyterHub uses dummy authentication; notebook execution is checked inside the spawned notebook Pod.',
                      'Superset saves and queries dashboard data through its Python application; browser rendering is not tested.',
                      'pgAdmin connects using its configured server definition from its Pod; the browser query tool is not tested.',
                      'Rancher uses verified HTTPS through its Service and configured hostname; external ingress routing is not tested.',
                      'Reduced resources and synthetic data; this is not a load, HA or production security test.']}
        private(self.path / 'report.json', json.dumps(report, indent=2) + '\n')
        lines = [self.id] + [f"{r['component']}: {r['status']} ({r['duration_seconds']}s) {r['detail']}" for r in self.rows]
        private(self.path / 'report.txt', '\n'.join(lines) + '\n')

    def run(self):
        self.path.mkdir(parents=True, exist_ok=bool(getattr(self.args, 'resume_run', None)), mode=0o700)
        started = time.monotonic()
        components = selection(self.args.components)
        failed = False
        try:
            self.preflight()
            self.record('preflight', 'PASS', started)
            if self.args.mode == 'check':
                for name in ['install-k3s', *components]:
                    self.record(name, 'NOT_RUN', time.monotonic(), 'Preflight only; use --run to install and test.')
                return 0
            self.current = 'bootstrap'
            started = time.monotonic()
            print('bootstrap: RUNNING — ' + ('reuse verified native installation' if getattr(self.args, 'resume_run', None)
                                            else 'article install-k3s.sh on native systemd host'), flush=True)
            self.bootstrap()
            self.record('bootstrap', 'PASS', started)
            for index, name in enumerate(components):
                self.current = name
                started = time.monotonic()
                print(name + ': RUNNING — ' + PURPOSES[name], flush=True)
                bad = [dependency for dependency in STAGES[name]
                       if next(row for row in self.rows if row['component'] == dependency)['status'] != 'PASS']
                if bad:
                    self.record(name, 'BLOCKED', started, 'Dependencies did not pass: ' + ', '.join(bad))
                    failed = True
                    continue
                try:
                    getattr(self, name.replace('-', '_'))()
                except Blocked as error:
                    self.record(name, 'BLOCKED', started, str(error))
                    failed = True
                except Exception as error:
                    self.record(name, 'FAIL', started, str(error))
                    failed = True
                    try:
                        self.diagnostics()
                    except Exception:
                        pass
                else:
                    self.record(name, 'PASS', started)
                try:
                    self.release_unused(components[index + 1:])
                except Exception as error:
                    self.record(name + '-cleanup', 'FAIL', time.monotonic(), str(error))
                    failed = True
        except (Exception, KeyboardInterrupt) as error:
            failed = True
            self.record(self.current, 'BLOCKED' if isinstance(error, Blocked) else 'FAIL', started,
                        str(error) or 'Interrupted')
            existing = {row['component'] for row in self.rows}
            for name in ['install-k3s', *components]:
                if name not in existing:
                    self.record(name, 'NOT_RUN', time.monotonic(), 'Installation prerequisites or bootstrap did not complete.')
        finally:
            self.current = 'cleanup'
            cleanup_started = time.monotonic()
            try:
                if self.created:
                    try:
                        self.diagnostics()
                    except Exception as error:
                        print('Diagnostic collection incomplete: ' + self.clean(str(error))[:250], flush=True)
                    if self.previous_map_count is not None:
                        try:
                            self.root_command(['sysctl', '-w', 'vm.max_map_count=' + str(self.previous_map_count)])
                        except Exception as error:
                            failed = True
                            self.record('kernel-cleanup', 'FAIL', cleanup_started, str(error))
                    if not self.args.keep:
                        self.cleanup_workloads()
                detail = ('Native K3s retained; ' + ('test workloads retained.' if self.args.keep else 'test namespace deletion requested.')) if self.created else 'No native installation attempted.'
                self.record('cleanup', 'PASS', cleanup_started, detail)
            except Exception as error:
                failed = True
                self.record('cleanup', 'FAIL', cleanup_started, str(error))
            self.report()
            if self.created:
                private(self.path / 'native.json', json.dumps({'k3s': self.k3s, 'namespaces': sorted(self.namespaces)}))
            print('Report: ' + str(self.path / 'report.json'), flush=True)
        return 1 if failed else 0


def cleanup(run_id):
    if not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{6}', run_id):
        raise ValueError('Invalid run ID')
    path = STATE / 'runs' / run_id
    state = json.loads((path / 'native.json').read_text())
    client = [state['k3s'], 'kubectl', '--kubeconfig', str(path / 'kubeconfig'), '--request-timeout=30s']
    result = subprocess.run(client + ['get', 'namespace', 'alias-smoke-control', '-o', 'json'],
                            capture_output=True, text=True, check=True)
    if json.loads(result.stdout).get('metadata', {}).get('labels', {}).get(LABEL) != run_id:
        raise ValueError('Cluster ownership label does not match; refusing cleanup')
    for name in state['namespaces']:
        if name == 'alias-smoke-control':
            continue
        result = subprocess.run(client + ['get', 'namespace', name, '--ignore-not-found', '-o', 'json'],
                                capture_output=True, text=True, check=True)
        if not result.stdout.strip():
            continue
        if json.loads(result.stdout).get('metadata', {}).get('labels', {}).get(LABEL) != run_id:
            raise ValueError('Namespace ownership label does not match; refusing cleanup: ' + name)
        subprocess.run(client + ['delete', 'namespace', name, '--wait=false'], check=True)
    print('Test namespace deletion requested; native K3s remains installed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan', dest='mode', action='store_const', const='plan', help='print coverage without downloads or cluster changes (default)')
    modes.add_argument('--check', dest='mode', action='store_const', const='check', help='check local prerequisites and write report')
    modes.add_argument('--run', dest='mode', action='store_const', const='run', help='execute install-k3s.sh, then install/test Kubernetes components')
    modes.add_argument('--cleanup', metavar='RUN_ID', help='delete owned test namespaces; retain the native K3s installation')
    parser.set_defaults(mode='plan')
    parser.add_argument('--test-host', choices=('native', 'docker'), default='native',
                        help='native host, or an Ubuntu/systemd Docker host running the same installer')
    parser.add_argument('--resume-run', help='retry service checks in an owned run with an unchanged, previously verified installer')
    parser.add_argument('--resume-host', help='reuse an owned Docker test host and its verified native run')
    parser.add_argument('--components', default='all', help='comma-separated components, all, or local (all except multi-host GlusterFS); dependencies are included')
    parser.add_argument('--timeout', type=int, default=900, help='seconds per deployment/probe (default 900)')
    parser.add_argument('--build-timeout', type=int, default=3600, help='seconds per custom image build/push')
    parser.add_argument('--keep', action='store_true', help='retain test namespaces/PVCs for inspection (native K3s always remains installed)')
    args = parser.parse_args()
    if args.timeout < 1 or args.build_timeout < 1:
        parser.error('timeouts must be positive')
    if args.resume_host and args.test_host != 'docker':
        parser.error('--resume-host requires --test-host docker')
    if args.resume_run and args.test_host != 'native':
        parser.error('--resume-run is for native runs; use --resume-host for Docker test hosts')
    try:
        components = selection(args.components)
        if args.cleanup:
            cleanup(args.cleanup)
            return 0
        if args.mode == 'plan':
            print('Native article install-k3s.sh -> Ready node/CoreDNS -> Kubernetes components -> functional checks.')
            print('K3s includes containerd; image builds run in a Kubernetes BuildKit Pod. No host Docker is required.')
            for component in components:
                print(component + ': ' + PURPOSES[component])
            print('Use --check for prerequisites or --run to install and execute. Full coverage reports GlusterFS as BLOCKED.')
            return 0
        if args.test_host == 'docker':
            if args.mode != 'run':
                parser.error('--test-host docker requires --run (or install-k3s.sh --smoke)')
            from smoke_docker_host import run as run_docker_host
            return run_docker_host(args)
        os.umask(0o077)
        return Lab(args).run()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    sys.exit(main())
