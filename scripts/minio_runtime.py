"""Independent MinIO configuration; no cluster calls during validation/rendering."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def setting(name, default=''):
    return os.environ.get(name) or default


def label(value, field):
    if len(value) > 63 or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', value):
        raise ValueError(field + ' must be a lowercase DNS label')
    return value


def names(value, field):
    values = value.split(',') if value else []
    return sorted({label(v.strip(), field) for v in values})


def credential(name):
    value = setting(name)
    # Also keeps the bootstrap shell/CLI and connection exports unambiguous.
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', value):
        raise ValueError(name + ' must contain 16..128 ASCII letters, digits, underscores or hyphens')
    return value


def quantity(value, field, cpu=False):
    pattern = r'(?:[1-9][0-9]*m|[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)' if cpu else r'[1-9][0-9]*(?:Mi|Gi|Ti)'
    if not re.fullmatch(pattern, value):
        raise ValueError(field + ' must be a positive Kubernetes resource quantity')
    if cpu:
        return float(value[:-1]) / 1000 if value.endswith('m') else float(value)
    return int(value[:-2]) * {'Mi': 1, 'Gi': 1024, 'Ti': 1024 ** 2}[value[-2:]]


def build():
    image = setting('MINIO_IMAGE')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[a-f0-9]{64}', image):
        raise ValueError('MINIO_IMAGE must be the built server/client image pinned with @sha256:<64 hex digits>')
    claim = setting('MINIO_EXISTING_CLAIM')
    storage_class = setting('MINIO_STORAGE_CLASS')
    if bool(claim) == bool(storage_class):
        raise ValueError('Set exactly one of MINIO_STORAGE_CLASS or MINIO_EXISTING_CLAIM')
    if claim:
        label(claim, 'MINIO_EXISTING_CLAIM')
    if storage_class and not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]|[a-z0-9]', storage_class):
        raise ValueError('MINIO_STORAGE_CLASS must be a storage class name')
    size = setting('MINIO_STORAGE_SIZE', '50Gi')
    quantity(size, 'MINIO_STORAGE_SIZE')
    resources = {'requests': {}, 'limits': {}}
    for kind, suffix in [('cpu', 'CPU'), ('memory', 'MEMORY')]:
        request = setting('MINIO_' + suffix + '_REQUEST', '250m' if kind == 'cpu' else '512Mi')
        limit = setting('MINIO_' + suffix + '_LIMIT', '1' if kind == 'cpu' else '1Gi')
        if quantity(request, suffix, kind == 'cpu') > quantity(limit, suffix, kind == 'cpu'):
            raise ValueError('MINIO_' + suffix + '_REQUEST must not exceed its limit')
        resources['requests'][kind], resources['limits'][kind] = request, limit
    root_user = credential('MINIO_ROOT_USER')
    root_password = credential('MINIO_ROOT_PASSWORD')
    secrets = [{'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': 'minio-root', 'namespace': 'minio'},
                'stringData': {'rootUser': root_user, 'rootPassword': root_password}}]
    clients = []
    access_keys = {root_user}
    passwords = {root_password}
    for name in names(setting('MINIO_CLIENTS', 'mlflow'), 'MINIO_CLIENTS'):
        if len(name) > 40:
            raise ValueError('MinIO client names must be at most 40 characters')
        prefix = 'MINIO_' + name.upper().replace('-', '_')
        buckets = names(setting(prefix + '_BUCKETS', name), prefix + '_BUCKETS')
        if not buckets or any(len(b) < 3 for b in buckets):
            raise ValueError(prefix + '_BUCKETS must list bucket names of 3..63 characters')
        access, password = credential(prefix + '_ACCESS_KEY'), credential(prefix + '_SECRET_KEY')
        if access in access_keys or password in passwords:
            raise ValueError('Each MinIO account must have distinct access and secret keys')
        access_keys.add(access)
        passwords.add(password)
        secret_name = 'minio-client-' + name
        secrets.append({'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                        'metadata': {'name': secret_name, 'namespace': 'minio'},
                        'stringData': {'accessKey': access, 'secretKey': password}})
        statements = [
            {'Effect': 'Allow', 'Action': ['s3:GetBucketLocation', 's3:ListBucket', 's3:ListBucketMultipartUploads'],
             'Resource': ['arn:aws:s3:::' + b for b in buckets]},
            {'Effect': 'Allow', 'Action': ['s3:GetObject', 's3:PutObject', 's3:DeleteObject',
                                          's3:AbortMultipartUpload', 's3:ListMultipartUploadParts'],
             'Resource': ['arn:aws:s3:::' + b + '/*' for b in buckets]}]
        clients.append({'name': name, 'secretName': secret_name, 'buckets': buckets,
                        'policy': {'Version': '2012-10-17', 'Statement': statements}})
    tls_secret = setting('MINIO_TLS_SECRET')
    if tls_secret:
        label(tls_secret, 'MINIO_TLS_SECRET')
    pull_secret = setting('MINIO_IMAGE_PULL_SECRET')
    if pull_secret:
        label(pull_secret, 'MINIO_IMAGE_PULL_SECRET')
    values = {'image': image, 'imagePullSecret': pull_secret,
              'persistence': {'existingClaim': claim, 'storageClass': storage_class, 'size': size},
              'resources': resources, 'tlsSecret': tls_secret, 'clients': clients,
              'allowedNamespaces': names(setting('MINIO_ALLOWED_NAMESPACES', 'mlflow'), 'MINIO_ALLOWED_NAMESPACES')}
    return secrets, values


def preflight(values):
    """Read-only checks before creating Secrets or invoking Helm."""
    def get(kind, name):
        result = subprocess.run(['kubectl', 'get', kind, name, '--namespace', 'minio',
                                 '--ignore-not-found', '-o', 'json'], capture_output=True, text=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else {}
    claim = values['persistence']['existingClaim'] or 'minio-data'
    deployment = get('deployment', 'minio')
    if deployment:
        volumes = deployment['spec']['template']['spec']['volumes']
        current = next(v['persistentVolumeClaim']['claimName'] for v in volumes if v['name'] == 'data')
        if current != claim:
            raise ValueError('Changing MinIO data claims requires a separate data migration; deployment refused')
    pvc = get('pvc', claim)
    if values['persistence']['existingClaim']:
        if pvc.get('status', {}).get('phase') != 'Bound':
            raise ValueError('MINIO_EXISTING_CLAIM must exist and be Bound in namespace minio')
        if pvc.get('spec', {}).get('volumeMode', 'Filesystem') != 'Filesystem':
            raise ValueError('MinIO requires a filesystem PVC')
        result = subprocess.run(['kubectl', 'get', 'pods', '--namespace', 'minio', '-o', 'json'],
                                capture_output=True, text=True, check=True)
        for pod in json.loads(result.stdout)['items']:
            mounts_claim = any(v.get('persistentVolumeClaim', {}).get('claimName') == claim
                               for v in pod.get('spec', {}).get('volumes', []))
            is_minio = pod.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/name') == 'alias-minio'
            if mounts_claim and not is_minio:
                raise ValueError('MINIO_EXISTING_CLAIM is mounted by another workload; use a dedicated data claim')
    elif pvc:
        if pvc.get('spec', {}).get('storageClassName') != values['persistence']['storageClass']:
            raise ValueError('Changing the MinIO StorageClass requires a data migration')
        old_size = pvc['spec']['resources']['requests']['storage']
        if old_size != values['persistence']['size']:
            raise ValueError('Resize the PVC separately before changing MINIO_STORAGE_SIZE')
    if values['tlsSecret']:
        secret = get('secret', values['tlsSecret'])
        if not all(key in secret.get('data', {}) for key in ('tls.crt', 'tls.key')):
            raise ValueError('MINIO_TLS_SECRET must contain tls.crt and tls.key in namespace minio')


def write_connection(client, destination):
    secrets, values = build()
    profile = next((c for c in values['clients'] if c['name'] == client), None)
    if not profile:
        raise ValueError('Client is not present in MINIO_CLIENTS')
    credentials = next(s['stringData'] for s in secrets if s['metadata']['name'] == profile['secretName'])
    endpoint = ('https' if values['tlsSecret'] else 'http') + '://minio.minio.svc.cluster.local:9000'
    prefix = 'MLFLOW_S3_' if client == 'mlflow' else 'S3_'
    data = {prefix + 'ENDPOINT_URL': endpoint, prefix + 'BUCKET': profile['buckets'][0]}
    if client == 'mlflow':
        data.update(MLFLOW_S3_ACCESS_KEY_ID=credentials['accessKey'], MLFLOW_S3_SECRET_ACCESS_KEY=credentials['secretKey'])
    else:
        data.update(AWS_ACCESS_KEY_ID=credentials['accessKey'], AWS_SECRET_ACCESS_KEY=credentials['secretKey'])
    path = Path(destination)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('# Load only for the selected consumer; contains private credentials.\n')
        stream.writelines(k + '=' + shlex.quote(v) + '\n' for k, v in data.items())
    print('Connection file created with mode 600; existing consumer configuration was not changed.')


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'values':
            print(json.dumps(build()[1]))
        elif sys.argv[1] == 'preflight':
            preflight(build()[1])
        elif sys.argv[1] == 'connection' and len(sys.argv) == 4:
            write_connection(sys.argv[2], sys.argv[3])
        else:
            raise ValueError('Use values, preflight, or connection CLIENT OUTPUT')
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, ValueError) else 'MinIO preparation failed; no credentials were printed.', file=sys.stderr)
        sys.exit(1)
