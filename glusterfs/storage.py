"""GlusterFS host provisioning and static NFSv4 PVs; no Kubernetes legacy driver."""
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MANAGER = 'alias-glusterfs'
GANESHA_CONFIG = Path('/etc/ganesha/ganesha.conf')
PROFILES = {
    'jupyterhub': ('jupyterhub', 'nfs-share-pvc', 'notebooks', '30Gi', 'NOTEBOOK', 1000, 100),
    'airflow': ('airflow', 'airflow-share-dag-pvc', 'dags', '5Gi', 'DAGS', 50000, 0),
    'spark-operator': ('spark-operator', 'airflow-share-dag-pvc', 'dags', '5Gi', 'DAGS', 50000, 0),
    'registry': ('docker-registry', 'docker-registry-pv-claim', 'registry', '20Gi', 'REGISTRY', 1000, 1000),
}


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'{name} is required')
    return value


def hostname(value):
    if len(value) > 253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                                   for label in value.split('.')):
        raise ValueError('Expected an IPv4 address or DNS hostname: ' + value)
    return value


def volume():
    value = os.environ.get('GLUSTERFS_VOLUME', 'alias-data')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9-]{0,62}', value):
        raise ValueError('GLUSTERFS_VOLUME must be a simple volume name')
    return value


def topology():
    nodes = [hostname(node) for node in required('GLUSTERFS_NODES').split()]
    replica = int(os.environ.get('GLUSTERFS_REPLICA_COUNT', '3'))
    if replica not in (1, 3) or (replica == 1 and len(nodes) != 1) or len(nodes) % replica:
        raise ValueError('Use three replicas per group, or one node with replica count 1 for development')
    if len(set(node.lower() for node in nodes)) != len(nodes):
        raise ValueError('Storage nodes must be distinct')
    mount = os.environ.get('GLUSTERFS_BRICK_MOUNT', '/srv/glusterfs')
    path = PurePosixPath(mount)
    if not re.fullmatch(r'/[a-zA-Z0-9/_-]+', mount) or '..' in path.parts or len(path.parts) < 3:
        raise ValueError('GLUSTERFS_BRICK_MOUNT must be a dedicated absolute mount path')
    return nodes, replica, str(path / volume() / 'brick')


def profiles():
    names = os.environ.get('GLUSTERFS_PROFILES', 'jupyterhub,airflow,spark-operator').split(',')
    if not names or any(name not in PROFILES for name in names) or len(set(names)) != len(names):
        raise ValueError('GLUSTERFS_PROFILES must select distinct supported profiles')
    return {name: PROFILES[name] for name in names}


def packages(role):
    locked = json.loads((ROOT / 'versions.lock.json').read_text())['glusterfs']['packages']
    common = ['glusterfs-common', 'glusterfs-client', 'glusterfs-cli',
              'libgfapi0', 'libgfrpc0', 'libgfxdr0', 'libglusterd0', 'libglusterfs0']
    names = {'server': common + ['glusterfs-server'],
             'gateway': common + ['nfs-ganesha', 'nfs-ganesha-gluster', 'nfs-common'],
             'client': ['nfs-common']}[role]
    return [name + '=' + locked[name] for name in names]


def check_host(role):
    if os.geteuid() != 0:
        raise ValueError('Run host provisioning as root')
    for package in packages(role):
        name, desired = package.split('=', 1)
        if run(['dpkg-query', '-W', '-f=${Version}', name]).strip() != desired:
            raise ValueError(f'Install the locked {role} packages first: {name}')


def volume_commands():
    nodes, replica, brick = topology()
    commands = [['gluster', '--mode=script', 'peer', 'probe', node] for node in nodes[1:]]
    create = ['gluster', '--mode=script', 'volume', 'create', volume()]
    if replica == 3:
        create += ['replica', '3']
    commands += [create + ['transport', 'tcp'] + [f'{node}:{brick}' for node in nodes],
                 ['gluster', '--mode=script', 'volume', 'start', volume()]]
    return commands


def create_volume():
    nodes, replica, brick = topology()
    check_host('server')
    # Query all volumes successfully before deciding one is absent. Never treat
    # a daemon/network error as permission to recreate an existing volume.
    tree = ET.fromstring(run(['gluster', '--xml', 'volume', 'info', 'all']))
    if tree.findtext('opRet') != '0':
        raise ValueError('Could not read GlusterFS volume inventory')
    existing = next((v for v in tree.findall('.//volumes/volume') if v.findtext('name') == volume()), None)
    if existing is not None:
        bricks = [item.findtext('name') for item in existing.findall('./bricks/brick')]
        if bricks != [f'{node}:{brick}' for node in nodes] or int(existing.findtext('replicaCount', '0')) != replica:
            raise ValueError('Existing volume topology differs; perform a separate storage migration')
        if existing.findtext('status') != '1':
            run(['gluster', '--mode=script', 'volume', 'start', volume()])
        return
    for command in volume_commands():
        run(command)


def ganesha():
    nodes, _, _ = topology()
    clients = []
    for item in required('GLUSTERFS_CLIENT_CIDRS').split(','):
        network = ipaddress.ip_network(item.strip(), strict=True)
        if network.prefixlen == 0 or network.is_multicast or network.is_loopback:
            raise ValueError('NFS clients must be explicit trusted node networks/IPs')
        clients.append(str(network))
    return f'''# Managed by {MANAGER}
NFS_CORE_PARAM {{ Protocols = 4; }}
EXPORT {{
    Export_Id = 1;
    Path = "/";
    Pseudo = "/{volume()}";
    Protocols = 4;
    Transports = TCP;
    SecType = sys;
    Access_Type = None;
    Squash = Root_Squash;
    FSAL {{ Name = GLUSTER; Hostname = "{nodes[0]}"; Volume = "{volume()}"; }}
    CLIENT {{
        Clients = {', '.join(clients)};
        Access_Type = RW;
        Squash = No_Root_Squash;
    }}
}}
'''


def directory_owners():
    owners = {}
    for _, _, directory, _, key, uid, gid in profiles().values():
        uid = int(os.environ.get(f'GLUSTERFS_{key}_UID', str(uid)))
        gid = int(os.environ.get(f'GLUSTERFS_{key}_GID', str(gid)))
        if not 0 <= uid < 2**32 - 1 or not 0 <= gid < 2**32 - 1:
            raise ValueError('Directory owners must be valid numeric UIDs/GIDs')
        owners[directory] = (uid, gid)
    return owners


def initialize_directories(mount, owners):
    for directory, (uid, gid) in owners.items():
        path = mount / directory
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError('Shared path must be a directory: ' + directory)
        if not path.exists():
            path.mkdir(mode=0o770)
            os.chown(path, uid, gid)
            path.chmod(0o2770)
        # Never recursively change permissions/ownership of existing data.


def configure_gateway():
    config, owners = ganesha(), directory_owners()  # Validate before writes.
    nodes, _, _ = topology()
    check_host('gateway')
    target = GANESHA_CONFIG
    if target.is_symlink():
        raise ValueError('Refusing a symlinked Ganesha configuration')
    previous = target.read_text() if target.exists() else None
    if previous is not None and previous != config:
        if not previous.startswith('# Managed by ' + MANAGER):
            raise ValueError('Existing Ganesha configuration is unmanaged; back it up and move it aside explicitly')
        state = subprocess.run(['systemctl', 'is-active', '--quiet', 'nfs-ganesha'], capture_output=True)
        if state.returncode == 0:
            raise ValueError('Stop Ganesha explicitly before changing a managed export configuration')
    # Do not use TemporaryDirectory: if unmount fails, recursive cleanup could
    # delete files on the shared volume. A failed unmount preserves the mount.
    mount = Path(tempfile.mkdtemp(prefix='alias-glusterfs-'))
    mounted = False
    try:
        run(['mount', '-t', 'glusterfs', f'{nodes[0]}:/{volume()}', str(mount)])
        mounted = True
        initialize_directories(mount, owners)
    finally:
        if mounted:
            run(['umount', str(mount)])
        mount.rmdir()
    if previous != config:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as temporary:
            temporary.write(config)
            candidate = Path(temporary.name)
        try:
            candidate.chmod(0o640)
            candidate.replace(target)
        finally:
            candidate.unlink(missing_ok=True)
    run(['systemctl', 'enable', '--now', 'nfs-ganesha'])
    run(['systemctl', 'is-active', '--quiet', 'nfs-ganesha'])


def manifests():
    server = hostname(required('GLUSTERFS_NFS_SERVER'))
    name = volume()
    docs, namespaces = [], set()
    for profile, (namespace, claim, directory, size, _, _, _) in profiles().items():
        if namespace not in namespaces:
            docs.append({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': namespace}})
            namespaces.add(namespace)
        pv = 'glusterfs-' + profile
        labels = {'app.kubernetes.io/managed-by': MANAGER}
        docs += [
            {'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': pv, 'labels': labels},
             'spec': {'capacity': {'storage': size}, 'accessModes': ['ReadWriteMany'],
                      'volumeMode': 'Filesystem', 'persistentVolumeReclaimPolicy': 'Retain',
                      'storageClassName': '', 'mountOptions': ['nfsvers=4.1', 'hard', 'timeo=600', 'retrans=2'],
                      'claimRef': {'namespace': namespace, 'name': claim},
                      'nfs': {'server': server, 'path': f'/{name}/{directory}', 'readOnly': False}}},
            {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
             'metadata': {'name': claim, 'namespace': namespace, 'labels': labels},
             'spec': {'storageClassName': '', 'volumeName': pv, 'volumeMode': 'Filesystem',
                      'accessModes': ['ReadWriteMany'], 'resources': {'requests': {'storage': size}}}},
        ]
    return docs


def contains(current, desired):
    if isinstance(desired, dict):
        return isinstance(current, dict) and all(key in current and contains(current[key], value)
                                                 for key, value in desired.items())
    return current == desired


def deploy():
    documents = manifests()  # No cluster writes until all configuration is valid.
    for doc in documents:
        if doc['kind'] == 'Namespace':
            continue
        args = ['kubectl', 'get', doc['kind'], doc['metadata']['name'], '--ignore-not-found', '-o', 'json']
        if 'namespace' in doc['metadata']:
            args += ['--namespace', doc['metadata']['namespace']]
        text = run(args)
        if text.strip():
            current = json.loads(text)
            # Kubernetes omits empty/default scalar fields in PV responses.
            spec = current.setdefault('spec', {})
            spec.setdefault('storageClassName', '')
            if 'nfs' in spec:
                spec['nfs'].setdefault('readOnly', False)
            if current.get('metadata', {}).get('deletionTimestamp') or not contains(current, doc):
                raise ValueError('Existing volume/claim differs or is unmanaged; migrate separately: ' + doc['metadata']['name'])
    run(['kubectl', 'apply', '-f', '-'], input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}))
    print('Applied static GlusterFS-backed NFS volumes. Check PVC binding and pod access separately.')


def main():
    action = sys.argv[1]
    if action == 'packages':
        print('\n'.join(packages(sys.argv[2])))
    elif action == 'validate-volume':
        topology()
    elif action == 'prepare-brick':
        _, _, brick = topology()
        mount = Path(brick).parents[1]
        if mount.resolve() != mount or not mount.is_mount() or Path(brick).parent.is_symlink() or Path(brick).is_symlink():
            raise ValueError('Use a mounted dedicated filesystem and real brick directories, not symlinks')
        Path(brick).mkdir(parents=True, exist_ok=True)
    elif action == 'volume-plan':
        print('\n'.join(shlex.join(command) for command in volume_commands()))
    elif action == 'create-volume':
        create_volume()
    elif action == 'ganesha':
        print(ganesha(), end='')
    elif action == 'configure-gateway':
        configure_gateway()
    elif action == 'manifests':
        print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': manifests()}, indent=2))
    elif action == 'deploy':
        deploy()
    else:
        raise ValueError('Unknown storage action')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, ET.ParseError, subprocess.CalledProcessError) as error:
        print('GlusterFS configuration failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
