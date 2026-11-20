#!/usr/bin/env python3
"""Interactive local-only configuration; never installs or contacts a cluster."""
import argparse
import os
from pathlib import Path
import secrets
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from minio_runtime import build, names


def ask(prompt, default=''):
    value = input(prompt + (f' [{default}]' if default else '') + ': ').strip()
    return value or default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('.env'))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; edit it deliberately or choose a new --output')
    print('MinIO opcional: servidor separado AGPLv3; blueprint Apache-2.0.')
    print('A release Community esta arquivada. Use a imagem compilada da origem fixada; veja minio/README.md.')
    config = {'MINIO_IMAGE': ask('Imagem compilada no registro, incluindo @sha256:...')}
    config['MINIO_IMAGE_PULL_SECRET'] = ask('Secret de pull no namespace minio, se o registro for privado')
    storage = ask('Armazenamento: storageclass ou pvc', 'storageclass')
    if storage not in ('storageclass', 'pvc'):
        raise ValueError('Escolha storageclass ou pvc')
    config['MINIO_STORAGE_CLASS'] = ask('StorageClass existente', 'local-path') if storage == 'storageclass' else ''
    config['MINIO_EXISTING_CLAIM'] = ask('PVC dedicado existente e Bound no namespace minio') if storage == 'pvc' else ''
    config['MINIO_STORAGE_SIZE'] = ask('Capacidade', '50Gi')
    for suffix, prompt, default in [('CPU_REQUEST', 'CPU reservada', '250m'), ('CPU_LIMIT', 'Limite de CPU', '1'),
                                     ('MEMORY_REQUEST', 'Memoria reservada', '512Mi'), ('MEMORY_LIMIT', 'Limite de memoria', '1Gi')]:
        config['MINIO_' + suffix] = ask(prompt, default)
    config['MINIO_TLS_SECRET'] = ask('Secret TLS existente no namespace minio (vazio para HTTP privado)')
    config['MINIO_ALLOWED_NAMESPACES'] = ask('Namespaces consumidores permitidos, separados por virgula', 'mlflow')
    config['MINIO_CLIENTS'] = ask('Perfis de clientes, separados por virgula', 'mlflow')
    for name in names(config['MINIO_CLIENTS'], 'MINIO_CLIENTS'):
        prefix = 'MINIO_' + name.upper().replace('-', '_')
        config[prefix + '_BUCKETS'] = ask(f'Buckets privados do perfil {name}', name)
        config[prefix + '_ACCESS_KEY'] = secrets.token_hex(12)
        config[prefix + '_SECRET_KEY'] = secrets.token_urlsafe(32)
    config['MINIO_ROOT_USER'] = secrets.token_hex(12)
    config['MINIO_ROOT_PASSWORD'] = secrets.token_urlsafe(32)
    previous = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(config)
        build()
    finally:
        os.environ.clear()
        os.environ.update(previous)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('# Generated locally; private credentials. Never commit.\n')
        stream.writelines(k + '=' + shlex.quote(v) + '\n' for k, v in config.items())
    print('Configuracao criada com permissao 600. Nenhum recurso do cluster foi alterado.')
    print('Selecione o arquivo com ALIAS_ENV_FILE e execute bash minio/deploy.sh --render para revisar.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, EOFError) as error:
        print(str(error) if isinstance(error, ValueError) else 'Configuracao interrompida; nenhuma credencial foi exibida.', file=sys.stderr)
        sys.exit(1)
