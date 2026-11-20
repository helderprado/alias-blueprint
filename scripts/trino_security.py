"""Generate and preserve local Trino authentication and TLS material."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import bcrypt

ROOT = Path(__file__).resolve().parents[1]
FILES = ('ca.pem', 'ca-key.pem', 'server.pem', 'server-key.pem', 'server-bundle.pem', 'password.db', 'identity.json')


def identity():
    user = os.environ.get('TRINO_USER', '')
    password = os.environ.get('TRINO_PASSWORD', '')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,63}', user):
        raise ValueError('Set TRINO_USER to a valid application username')
    if not 16 <= len(password.encode()) <= 72:
        raise ValueError('TRINO_PASSWORD must contain 16..72 UTF-8 bytes')
    return user, password


def command(args):
    return subprocess.run(args, check=True, capture_output=True)


def material():
    user, password = identity()
    directory = ROOT / 'trino/runtime-creds'
    if not all((directory / name).is_file() for name in FILES):
        raise ValueError('Run bash trino/gen-security.sh first')
    if json.loads((directory / 'identity.json').read_text()) != {'user': user}:
        raise ValueError('Existing Trino identity differs; plan credential changes separately')
    line = (directory / 'password.db').read_text().strip()
    name, encoded = line.split(':', 1)
    if name != user or not bcrypt.checkpw(password.encode(), encoded.encode()):
        raise ValueError('Existing Trino password differs; existing material was preserved')
    command(['openssl', 'verify', '-CAfile', str(directory / 'ca.pem'), str(directory / 'server.pem')])
    return directory


def bootstrap():
    user, password = identity()
    directory = ROOT / 'trino/runtime-creds'
    if any((directory / name).exists() for name in FILES):
        material()
        return
    if (ROOT / '.git').exists():
        if command(['git', '-C', str(ROOT), 'ls-files', '--', 'trino/runtime-creds/']).stdout:
            raise ValueError('Trino bootstrap output must not be tracked')
        command(['git', '-C', str(ROOT), 'check-ignore', '-q', '--', 'trino/runtime-creds/server-key.pem'])
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='.bootstrap-', dir=directory) as name:
        tmp = Path(name)
        command(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256', '-nodes', '-days', '3650',
                 '-keyout', str(tmp / 'ca-key.pem'), '-out', str(tmp / 'ca.pem'), '-subj', '/CN=ALIAS-Trino-CA'])
        command(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(tmp / 'server-key.pem')])
        command(['openssl', 'req', '-new', '-key', str(tmp / 'server-key.pem'), '-out', str(tmp / 'server.csr'), '-subj', '/CN=trino'])
        names = ['trino', 'trino.trino', 'trino.trino.svc', 'trino.trino.svc.cluster.local', 'localhost']
        (tmp / 'extensions.cnf').write_text('basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=serverAuth\nsubjectAltName=' + ','.join('DNS:' + x for x in names) + ',IP:127.0.0.1\n')
        command(['openssl', 'x509', '-req', '-in', str(tmp / 'server.csr'), '-CA', str(tmp / 'ca.pem'),
                 '-CAkey', str(tmp / 'ca-key.pem'), '-CAcreateserial', '-days', '825', '-sha256',
                 '-extfile', str(tmp / 'extensions.cnf'), '-out', str(tmp / 'server.pem')])
        (tmp / 'server-bundle.pem').write_bytes((tmp / 'server-key.pem').read_bytes() + (tmp / 'server.pem').read_bytes() + (tmp / 'ca.pem').read_bytes())
        (tmp / 'password.db').write_text(user + ':' + bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode() + '\n')
        (tmp / 'identity.json').write_text(json.dumps({'user': user}))
        for name in FILES:
            (tmp / name).chmod(0o600)
            (tmp / name).replace(directory / name)
    material()


if __name__ == '__main__':
    try:
        bootstrap()
        print('Trino local security material ready; existing material preserved.')
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        import sys
        print(str(error) if isinstance(error, ValueError) else 'Trino bootstrap failed; nothing was deployed.', file=sys.stderr)
        sys.exit(1)
