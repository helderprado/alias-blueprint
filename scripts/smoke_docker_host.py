"""Run the real native installer in an isolated Ubuntu/systemd Docker test host."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
HOST_LABEL = 'org.alias-blueprint.test-host'


def source_archive():
    files = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'])
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for raw in sorted(set(filter(None, files.decode().split('\0')))):
            path = ROOT / raw
            if path.is_symlink():
                raise ValueError('Source snapshot refuses symlinks: ' + raw)
            if path.is_file():
                archive.add(path, arcname=raw, recursive=False)
    return buffer.getvalue()


def run(args):
    if not shutil.which('docker'):
        raise ValueError('Docker is required only for --test-host docker.')
    os.umask(0o077)
    resume = getattr(args, 'resume_host', None)
    if resume and not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{6}', resume):
        raise ValueError('Invalid Docker host run ID')
    run_id = resume or (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(3))
    name = 'alias-article-test-' + run_id.lower()
    path = ROOT / '.local-smoke/hosts' / run_id
    path.mkdir(parents=True, exist_ok=bool(resume), mode=0o700)
    recipe = ROOT / 'scripts/smoke-host/Dockerfile'
    tag = 'alias-blueprint-smoke-host:' + hashlib.sha256(recipe.read_bytes()).hexdigest()[:12]
    created = False
    code = 1
    summary = {'run_id': run_id, 'environment': 'Ubuntu 22.04/systemd inside privileged Docker',
               'container': name, 'test_host_image': tag,
               'scope': 'Actual install-k3s.sh and Kubernetes operations; not a VM/bare-metal host validation.'}
    try:
        subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], check=True, timeout=60)
        if resume:
            previous = json.loads((path / 'host-report.json').read_text())
            if previous['container'] != name or len(previous.get('reports', [])) != 1:
                raise RuntimeError('The retained host must contain exactly one verified native run')
            owner = subprocess.check_output(['docker', 'inspect', '--format', '{{index .Config.Labels "' + HOST_LABEL + '"}}', name], text=True)
            if owner.strip() != run_id:
                raise RuntimeError('Docker host ownership label mismatch')
            native_run_id = Path(previous['reports'][0]).parent.name
        else:
            subprocess.run(['docker', 'build', '--tag', tag, str(recipe.parent)], check=True)
            subprocess.run(['docker', 'run', '--detach', '--name', name,
                            '--label', HOST_LABEL + '=' + run_id, '--privileged', '--cgroupns=private',
                            '--tmpfs', '/run', '--tmpfs', '/run/lock',
                            '--volume', '/var/lib/rancher/k3s', '--volume', '/var/lib/kubelet', tag], check=True)
        created = True
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = subprocess.run(['docker', 'exec', name, 'systemctl', 'is-system-running'],
                                   capture_output=True, text=True, timeout=20).stdout.strip()
            if state in ('running', 'degraded'):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Ubuntu/systemd test host did not become ready')
        packages = subprocess.check_output(['docker', 'exec', name, 'dpkg-query', '-W'])
        (path / 'host-packages.tsv').write_bytes(packages)
        subprocess.run(['docker', 'exec', '-i', name, 'tar', '-xzf', '-', '-C', '/workspace/alias-blueprint'],
                       input=source_archive(), check=True)
        subprocess.run(['docker', 'exec', '-w', '/workspace/alias-blueprint', name, 'git', 'init', '-q'], check=True)
        subprocess.run(['docker', 'exec', '-w', '/workspace/alias-blueprint', name, 'git', 'add', '-A'], check=True)
        # These caches contain public artifacts, not an existing run's credentials.
        cache = ROOT / '.local-smoke/cache/charts'
        if cache.exists():
            subprocess.run(['docker', 'exec', name, 'mkdir', '-p', '/workspace/alias-blueprint/.local-smoke/cache'], check=True)
            subprocess.run(['docker', 'cp', str(cache) + '/.', name + ':/workspace/alias-blueprint/.local-smoke/cache/charts'], check=True)
        helm = os.environ.get('ALIAS_HELM') or shutil.which('helm')
        if helm and Path(helm).is_file():
            subprocess.run(['docker', 'cp', helm, name + ':/usr/local/bin/helm'], check=True)
        command = ['docker', 'exec', '-w', '/workspace/alias-blueprint', name,
                   'bash', 'install-k3s.sh', '--smoke', '--components', args.components,
                   '--timeout', str(args.timeout), '--build-timeout', str(args.build_timeout)]
        if args.keep:
            command.append('--keep')
        if resume:
            command += ['--resume-run', native_run_id]
            summary['resumed'] = True
        print('Executing article installer and functional checks in ' + name, flush=True)
        code = subprocess.run(command).returncode
    except (OSError, subprocess.SubprocessError, RuntimeError, KeyboardInterrupt) as error:
        summary['error'] = str(error) or 'Interrupted'
        print('Docker test host failed: ' + summary['error'], flush=True)
    finally:
        if created:
            destination = path / 'artifacts'
            destination.mkdir(exist_ok=True, mode=0o700)
            copied = subprocess.run(['docker', 'cp', name + ':/workspace/alias-blueprint/.local-smoke/runs/.', str(destination)],
                                    capture_output=True, text=True)
            if copied.returncode:
                summary['artifact_error'] = copied.stderr.strip()
                code = 1
            else:
                summary['reports'] = [str(file.relative_to(path)) for file in destination.glob('*/report.json')]
            metadata = subprocess.run(['docker', 'inspect', '--format', '{{.Image}}', name], capture_output=True, text=True)
            summary['test_host_image_id'] = metadata.stdout.strip()
            if not args.keep:
                owner = subprocess.run(['docker', 'inspect', '--format', '{{index .Config.Labels "' + HOST_LABEL + '"}}', name],
                                       capture_output=True, text=True)
                if owner.stdout.strip() == run_id:
                    removed = subprocess.run(['docker', 'rm', '--force', '--volumes', name]).returncode == 0
                    summary['test_host_removed'] = removed
                    if not removed:
                        code = 1
                else:
                    summary['cleanup_error'] = 'Ownership label mismatch; test host retained'
                    code = 1
            else:
                summary['test_host_retained'] = True
        summary['exit_code'] = code
        (path / 'host-report.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('Host report: ' + str(path / 'host-report.json'), flush=True)
    return code
