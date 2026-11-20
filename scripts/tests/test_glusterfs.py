"""Offline storage checks: no packages, mounts, hosts or cluster writes."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('glusterfs_storage', ROOT / 'glusterfs/storage.py')
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class GlusterFSTests(unittest.TestCase):
    def setUp(self):
        self.env = {'GLUSTERFS_NODES': 'storage-1 storage-2 storage-3',
                    'GLUSTERFS_NFS_SERVER': 'gateway.example',
                    'GLUSTERFS_CLIENT_CIDRS': '10.20.0.0/24,10.21.0.4/32'}

    def test_render_entrypoints_are_offline_and_load_selected_env(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'selected.env'
            config.write_text('\n'.join(f'{key}={json.dumps(value)}' for key, value in self.env.items()))
            env = dict(os.environ, ALIAS_ENV_FILE=str(config))
            for script in ('create-volume.sh', 'gateway.sh', 'deploy.sh'):
                result = subprocess.run(['bash', str(ROOT / 'glusterfs' / script), '--render'],
                                        env=env, cwd=directory, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('VOLUME_PATH', result.stdout)
            documents = json.loads(result.stdout)['items']
            claims = [doc for doc in documents if doc['kind'] == 'PersistentVolumeClaim']
            self.assertEqual({(doc['metadata']['namespace'], doc['metadata']['name']) for doc in claims},
                             {('jupyterhub', 'nfs-share-pvc'), ('airflow', 'airflow-share-dag-pvc'),
                              ('spark-operator', 'airflow-share-dag-pvc')})
            pvs = [doc for doc in documents if doc['kind'] == 'PersistentVolume']
            self.assertEqual(pvs[1]['spec']['nfs'], pvs[2]['spec']['nfs'])
            for pv in pvs:
                self.assertEqual(pv['spec']['persistentVolumeReclaimPolicy'], 'Retain')
                self.assertEqual(pv['spec']['accessModes'], ['ReadWriteMany'])
                self.assertNotIn('local', pv['spec'])
                self.assertNotIn('glusterfs', pv['spec'])  # Removed Kubernetes driver.
                self.assertEqual(pv['spec']['nfs']['server'], 'gateway.example')

    def test_invalid_configuration_fails_before_external_commands(self):
        cases = [('topology', {'GLUSTERFS_NODES': 'one one one'}),
                 ('topology', {'GLUSTERFS_NODES': 'one two'}),
                 ('topology', {'GLUSTERFS_NODES': 'one;touch/x two three'}),
                 ('topology', {'GLUSTERFS_BRICK_MOUNT': '/'}),
                 ('topology', {'GLUSTERFS_BRICK_MOUNT': '/srv/../etc'}),
                 ('topology', {'GLUSTERFS_VOLUME': 'vol; bad'}),
                 ('ganesha', {'GLUSTERFS_CLIENT_CIDRS': '0.0.0.0/0'}),
                 ('ganesha', {'GLUSTERFS_CLIENT_CIDRS': '*'}),
                 ('ganesha', {'GLUSTERFS_CLIENT_CIDRS': ''}),
                 ('deploy', {'GLUSTERFS_NFS_SERVER': ''}),
                 ('deploy', {'GLUSTERFS_PROFILES': 'unknown'}),
                 ('deploy', {'GLUSTERFS_PROFILES': 'airflow,airflow'})]
        for action, override in cases:
            with self.subTest(action=action, override=override), patch.dict(os.environ, self.env | override, clear=True), patch.object(storage, 'run') as run:
                with self.assertRaises(ValueError):
                    getattr(storage, action)()
                run.assert_not_called()
        with patch.dict(os.environ, self.env, clear=True):
            export = storage.ganesha()
            self.assertIn('Access_Type = None;', export)
            self.assertIn('Clients = 10.20.0.0/24, 10.21.0.4/32;', export)
            self.assertIn('Protocols = 4;', export)
            self.assertNotIn('force', json.dumps(storage.volume_commands()))

    def test_deploy_rejects_existing_claim_before_any_write(self):
        for mismatch in ('unmanaged', 'legacy-local', 'deleting'):
            with self.subTest(mismatch=mismatch), patch.dict(os.environ, self.env, clear=True):
                documents = storage.manifests()
                existing = copy.deepcopy(next(doc for doc in documents if doc['kind'] == 'PersistentVolumeClaim'))
                if mismatch == 'unmanaged':
                    existing['metadata'].pop('labels')
                elif mismatch == 'legacy-local':
                    existing['spec']['volumeName'] = 'legacy-local-volume'
                else:
                    existing['metadata']['deletionTimestamp'] = '2026-11-20T00:00:00Z'
                def lookup(args, **kwargs):
                    self.assertEqual(args[:2], ['kubectl', 'get'])
                    return json.dumps(existing) if args[2] == 'PersistentVolumeClaim' else ''
                with patch.object(storage, 'run', side_effect=lookup), self.assertRaises(ValueError):
                    storage.deploy()

    def test_idempotent_deploy_accepts_kubernetes_defaults_and_retains_binding(self):
        with patch.dict(os.environ, self.env, clear=True):
            documents = storage.manifests()
            def respond(args, **kwargs):
                if args[1] == 'get':
                    doc = copy.deepcopy(next(item for item in documents if item['kind'] == args[2]
                                             and item['metadata']['name'] == args[3]
                                             and ('--namespace' not in args or item['metadata']['namespace'] == args[-1])))
                    if doc['kind'] == 'PersistentVolume':
                        doc['spec'].pop('storageClassName')
                        doc['spec']['nfs'].pop('readOnly')
                        doc['spec']['claimRef']['uid'] = 'existing-binding-uid'
                    return json.dumps(doc)
                applied = json.loads(kwargs['input'])['items']
                self.assertEqual(applied, documents)
                return ''
            with patch.object(storage, 'run', side_effect=respond) as run:
                storage.deploy()
                self.assertEqual(sum(call.args[0][1] == 'apply' for call in run.call_args_list), 1)

    def test_volume_inventory_error_or_topology_change_never_creates_volume(self):
        matching = '<cliOutput><opRet>0</opRet><volInfo><volumes><volume><name>alias-data</name><replicaCount>3</replicaCount><status>1</status><bricks>' + ''.join(
            f'<brick><name>storage-{n}:/srv/glusterfs/alias-data/brick</name></brick>' for n in (1, 2, 3)) + '</bricks></volume></volumes></volInfo></cliOutput>'
        with patch.dict(os.environ, self.env, clear=True), patch.object(storage, 'check_host'):
            for result in ('<cliOutput><opRet>-1</opRet></cliOutput>', matching.replace('storage-3:', 'other-host:')):
                with patch.object(storage, 'run', return_value=result) as run, self.assertRaises(ValueError):
                    storage.create_volume()
                self.assertEqual(run.call_count, 1)
            with patch.object(storage, 'run', return_value=matching) as run:
                storage.create_volume()
                self.assertEqual(run.call_count, 1)
            with patch.object(storage, 'run', side_effect=subprocess.CalledProcessError(1, 'gluster')) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    storage.create_volume()
                self.assertEqual(run.call_count, 1)

    def test_package_releases_are_exact_and_profile_versions_are_shared(self):
        for role in ('server', 'gateway', 'client'):
            for package in storage.packages(role):
                self.assertRegex(package, r'^[a-z0-9-]+=[0-9][a-zA-Z0-9:.+~-]+$')
        with patch.dict(os.environ, self.env | {'GLUSTERFS_PROFILES': 'registry'}, clear=True):
            claim = next(doc for doc in storage.manifests() if doc['kind'] == 'PersistentVolumeClaim')
            self.assertEqual(claim['metadata']['name'], 'docker-registry-pv-claim')
            self.assertEqual(storage.directory_owners(), {'registry': (1000, 1000)})

    def test_gateway_does_not_overwrite_unmanaged_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, self.env, clear=True):
            config = Path(directory) / 'ganesha.conf'
            config.write_text('# Existing unrelated exports\n')
            with patch.object(storage, 'GANESHA_CONFIG', config), patch.object(storage, 'check_host'), patch.object(storage, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'unmanaged'):
                    storage.configure_gateway()
                self.assertEqual(config.read_text(), '# Existing unrelated exports\n')
                run.assert_not_called()

    def test_failed_unmount_preserves_mount_and_does_not_install_export(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, self.env, clear=True):
            mount = Path(directory) / 'native-mount'
            mount.mkdir()
            config = Path(directory) / 'ganesha.conf'
            def respond(args, **kwargs):
                if args[0] == 'umount':
                    raise subprocess.CalledProcessError(1, args)
                self.assertEqual(args[0], 'mount')
                return ''
            with patch.object(storage, 'GANESHA_CONFIG', config), patch.object(storage, 'check_host'), patch.object(storage, 'initialize_directories'), patch.object(storage.tempfile, 'mkdtemp', return_value=str(mount)), patch.object(storage, 'run', side_effect=respond):
                with self.assertRaises(subprocess.CalledProcessError):
                    storage.configure_gateway()
                self.assertTrue(mount.is_dir())
                self.assertFalse(config.exists())

    def test_initialization_preserves_existing_data_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage.os, 'chown') as chown:
            root = Path(directory)
            existing = root / 'notebooks'
            existing.mkdir(mode=0o700)
            (existing / 'existing-data').write_text('preserve')
            storage.initialize_directories(root, {'notebooks': (1000, 100), 'dags': (50000, 0)})
            self.assertEqual((existing / 'existing-data').read_text(), 'preserve')
            self.assertEqual(existing.stat().st_mode & 0o7777, 0o700)
            self.assertEqual((root / 'dags').stat().st_mode & 0o7777, 0o2770)
            chown.assert_called_once_with(root / 'dags', 50000, 0)
            (root / 'registry').symlink_to(existing, target_is_directory=True)
            with self.assertRaises(ValueError):
                storage.initialize_directories(root, {'registry': (0, 0)})


if __name__ == '__main__':
    unittest.main()
