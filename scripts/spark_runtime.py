"""Bounded Spark jobs, namespace RBAC and optional storage; render without a cluster."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
import yaml

ROOT = Path(__file__).resolve().parents[1]


def setting(name, default=''):
    return os.environ.get(name) or default


def enabled(name):
    value = setting(name, 'false')
    if value not in ('true', 'false'):
        raise ValueError(name + ' must be true or false')
    return value == 'true'


def required(name, fallback=''):
    value = setting(name, setting(fallback) if fallback else '')
    if not value.strip():
        raise ValueError('Missing required variable: ' + name)
    return value


def label(value, name):
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', value) or len(value) > 50:
        raise ValueError(name + ' must be a lowercase DNS label of at most 50 characters')
    return value


def integer(name, default, maximum):
    value = int(setting(name, default))
    if not 1 <= value <= maximum:
        raise ValueError(name + ' is outside its supported positive range')
    return value


def cpu(value):
    if not re.fullmatch(r'[1-9][0-9]*(?:m)?', value):
        raise ValueError('CPU quantities must be positive whole cores or millicores')
    return int(value[:-1]) / 1000 if value.endswith('m') else int(value)


def memory(value, spark=False):
    pattern = r'[1-9][0-9]*[mg]' if spark else r'[1-9][0-9]*(?:Mi|Gi)'
    if not re.fullmatch(pattern, value):
        raise ValueError('Memory must use Spark m/g units or Kubernetes Mi/Gi units as appropriate')
    if spark:
        return int(value[:-1]) * (1024 if value.endswith('g') else 1)
    return int(value[:-2]) * (1024 if value.endswith('Gi') else 1)


def secret_data():
    data = {}
    if enabled('SPARK_S3_ENABLED'):
        data.update(AWS_ACCESS_KEY_ID=required('SPARK_S3_ACCESS_KEY_ID', 'AWS_ACCESS_KEY_ID'),
                    AWS_SECRET_ACCESS_KEY=required('SPARK_S3_SECRET_ACCESS_KEY', 'AWS_SECRET_ACCESS_KEY'))
    if enabled('SPARK_DB_ENABLED'):
        data.update(DATABASE_URL=required('SPARK_DB_URL'), DATABASE_USER=required('SPARK_DB_USER'),
                    DATABASE_PASSWORD=required('SPARK_DB_PASSWORD'))
    return data


def build():
    """Common runtime interface: credentials are only in the external Secret."""
    application()  # Validate the complete selected profile before cluster requests.
    data = secret_data()
    secrets = [{'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'spark-runtime', 'namespace': 'spark'},
                'type': 'Opaque', 'stringData': data}] if data else []
    return secrets, {}


def application():
    image = setting('SPARK_IMAGE')
    if not image:
        if enabled('SPARK_S3_ENABLED') or enabled('SPARK_DB_ENABLED'):
            raise ValueError('Set SPARK_IMAGE to the built S3/JDBC image digest for optional integrations')
        image = json.loads((ROOT / 'versions.lock.json').read_text())['images']['spark:3.5.0-scala2.12-java17-python3-ubuntu']
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[a-f0-9]{64}', image):
        raise ValueError('SPARK_IMAGE must contain an immutable registry SHA-256 digest')
    name = label(setting('SPARK_APPLICATION_NAME', 'alias-spark-smoke'), 'SPARK_APPLICATION_NAME')
    driver, executor = {}, {}
    for role, pod in [('DRIVER', driver), ('EXECUTOR', executor)]:
        cores = integer('SPARK_' + role + '_CORES', '1', 32)
        request = setting('SPARK_' + role + '_CPU_REQUEST', '500m')
        limit = setting('SPARK_' + role + '_CPU_LIMIT', str(cores))
        if cpu(request) > cpu(limit) or cores > cpu(limit):
            raise ValueError('Spark CPU requests and core count must not exceed their limit')
        mem = setting('SPARK_' + role + '_MEMORY', '512m' if role == 'DRIVER' else '1g')
        overhead = setting('SPARK_' + role + '_MEMORY_OVERHEAD', '384m')
        memory(mem, True)
        memory(overhead, True)
        pod.update(cores=cores, coreRequest=request, coreLimit=limit, memory=mem, memoryOverhead=overhead,
                   serviceAccount='spark', labels={'app.kubernetes.io/part-of': 'alias-spark'},
                   podSecurityContext={'runAsUser': 185, 'runAsGroup': 0, 'runAsNonRoot': True,
                                       'fsGroup': 0},
                   securityContext={'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                   volumeMounts=[{'name': 'smoke-code', 'mountPath': '/opt/spark/alias', 'readOnly': True}])
    executor['instances'] = integer('SPARK_EXECUTORS', '1', 32)
    quota = quotas()
    count = 1 + executor['instances']
    total_cpu = cpu(driver['coreLimit']) + executor['instances'] * cpu(executor['coreLimit'])
    total_memory = memory(driver['memory'], True) + memory(driver['memoryOverhead'], True) + executor['instances'] * (
        memory(executor['memory'], True) + memory(executor['memoryOverhead'], True))
    if total_cpu > cpu(quota['limits.cpu']) or total_memory > memory(quota['limits.memory']) or count > int(quota['pods']):
        raise ValueError('This application exceeds the configured namespace CPU, memory or Pod quota')
    spec = {'type': 'Python', 'pythonVersion': '3', 'mode': 'cluster', 'sparkVersion': '3.5.0',
            'image': image, 'imagePullPolicy': 'IfNotPresent',
            'mainApplicationFile': 'local:///opt/spark/alias/smoke.py',
            'restartPolicy': {'type': 'Never'}, 'timeToLiveSeconds': 600,
            'dynamicAllocation': {'enabled': False},
            'driver': driver, 'executor': executor,
            'volumes': [{'name': 'smoke-code', 'configMap': {'name': 'spark-smoke-code'}}],
            'sparkConf': {'spark.dynamicAllocation.enabled': 'false',
                          'spark.sql.shuffle.partitions': '2', 'spark.ui.enabled': 'false',
                          'spark.redaction.regex': '(?i)secret|password|token|access.key|AWS_ACCESS_KEY_ID|DATABASE_URL'}}
    pull_secret = setting('SPARK_IMAGE_PULL_SECRET')
    if pull_secret:
        spec['imagePullSecrets'] = [label(pull_secret, 'SPARK_IMAGE_PULL_SECRET')]
    pvc = setting('SPARK_DAGS_PVC')
    if pvc:
        label(pvc, 'SPARK_DAGS_PVC')
        spec['volumes'].append({'name': 'shared-files', 'persistentVolumeClaim': {'claimName': pvc, 'readOnly': True}})
        for pod in (driver, executor):
            pod['volumeMounts'].append({'name': 'shared-files', 'mountPath': '/opt/spark/shared', 'readOnly': True})
    data = secret_data()
    if data:
        for pod in (driver, executor):
            pod['envSecretKeyRefs'] = {name: {'name': 'spark-runtime', 'key': name} for name in data}
    if enabled('SPARK_S3_ENABLED'):
        endpoint = required('SPARK_S3_ENDPOINT_URL', 'S3_ENDPOINT_URL')
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('SPARK_S3_ENDPOINT_URL must be an HTTP(S) endpoint without credentials or paths')
        bucket = required('SPARK_S3_BUCKET', 'S3_BUCKET')
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
            raise ValueError('SPARK_S3_BUCKET must be a valid bucket name')
        # SparkApplication properties never carry passwords or access keys.
        spec['hadoopConf'] = {'fs.s3a.endpoint': endpoint.rstrip('/'), 'fs.s3a.path.style.access': 'true',
                             'fs.s3a.connection.ssl.enabled': str(parsed.scheme == 'https').lower(),
                             'fs.s3a.aws.credentials.provider': 'com.amazonaws.auth.EnvironmentVariableCredentialsProvider'}
        spec['arguments'] = ['--s3-prefix', 's3a://' + bucket + '/alias-smoke']
    return {'apiVersion': 'sparkoperator.k8s.io/v1beta2', 'kind': 'SparkApplication',
            'metadata': {'name': name, 'namespace': 'spark'}, 'spec': spec}


def quotas():
    cpu_limit = setting('SPARK_QUOTA_CPU', '4')
    mem_limit = setting('SPARK_QUOTA_MEMORY', '8Gi')
    cpu(cpu_limit)
    memory(mem_limit)
    return {'requests.cpu': cpu_limit, 'limits.cpu': cpu_limit,
            'requests.memory': mem_limit, 'limits.memory': mem_limit,
            'pods': str(integer('SPARK_QUOTA_PODS', '12', 1000)),
            'requests.ephemeral-storage': '8Gi', 'limits.ephemeral-storage': '16Gi'}


def resources():
    application()
    docs = []
    for name in ('namespace.yaml', 'service-account.yaml', 'service-account-role.yaml'):
        docs.extend(yaml.safe_load_all((ROOT / 'spark' / name).read_text()))
    docs.extend([
        {'apiVersion': 'v1', 'kind': 'ResourceQuota', 'metadata': {'name': 'spark-budget', 'namespace': 'spark'},
         'spec': {'hard': quotas()}},
        {'apiVersion': 'v1', 'kind': 'LimitRange', 'metadata': {'name': 'spark-defaults', 'namespace': 'spark'},
         'spec': {'limits': [{'type': 'Container', 'default': {'ephemeral-storage': '2Gi'},
                             'defaultRequest': {'ephemeral-storage': '512Mi'}}]}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'spark-smoke-code', 'namespace': 'spark'},
         'data': {'smoke.py': (ROOT / 'spark/examples/smoke.py').read_text()}}])
    return {'apiVersion': 'v1', 'kind': 'List', 'items': docs}


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs).stdout


def preflight_setup():
    text = run(['kubectl', 'get', 'clusterrolebinding', 'spark-role', '--ignore-not-found', '-o', 'json'])
    binding = json.loads(text) if text.strip() else {}
    if binding.get('roleRef', {}).get('name') == 'edit' and any(
            s.get('kind') == 'ServiceAccount' and s.get('name') == 'spark'
            and s.get('namespace') in ('spark', 'spark-operator') for s in binding.get('subjects', [])):
        raise ValueError('Legacy spark-role ClusterRoleBinding still grants cluster-wide edit; review/revoke it before setup')


def preflight_application(doc):
    pvc = setting('SPARK_DAGS_PVC')
    if pvc:
        current = json.loads(run(['kubectl', 'get', 'pvc', pvc, '-n', 'spark', '-o', 'json']))
        if current.get('status', {}).get('phase') != 'Bound':
            raise ValueError('SPARK_DAGS_PVC must be Bound in namespace spark')
    name = doc['metadata']['name']
    text = run(['kubectl', 'get', 'sparkapplication', name, '-n', 'spark', '--ignore-not-found', '-o', 'json'])
    if text.strip():
        raise ValueError('SparkApplication name already exists; choose a new SPARK_APPLICATION_NAME instead of resubmitting a running job')


def main():
    action = sys.argv[1]
    if action == 'verify-chart':
        expected = json.loads((ROOT / 'versions.lock.json').read_text())['charts']['spark-operator']['digest']
        if hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest() != expected:
            raise ValueError('Spark Operator chart archive SHA-256 does not match versions.lock.json')
    elif action == 'resources':
        print(json.dumps(resources(), indent=2))
    elif action == 'application':
        print(json.dumps(application(), indent=2))
    elif action == 'setup':
        documents = resources()
        preflight_setup()
        # Shared runtime helper validates every selected credential and refuses replacement.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='alias-spark-') as directory:
            run([sys.executable, str(ROOT / 'scripts/runtime-secrets.py'), 'spark', directory + '/values.json'])
        run(['kubectl', 'apply', '-f', '-'], input=json.dumps(documents))
        print('Spark namespace, scoped RBAC, runtime credentials and resource budget prepared.')
    elif action == 'submit':
        doc = application()
        preflight_application(doc)
        # Create, rather than apply, also closes the race with concurrent submissions.
        run(['kubectl', 'create', '-f', '-'], input=json.dumps(doc))
        print('Spark smoke application submitted; inspect its status and driver logs separately.')
    else:
        raise ValueError('Unknown Spark action')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Captured subprocess output may contain credentials; never echo it.
        print(str(error) if isinstance(error, ValueError) else 'Spark operation failed; no credentials were printed.', file=sys.stderr)
        sys.exit(1)
