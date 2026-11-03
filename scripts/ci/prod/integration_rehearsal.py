"""Run the real DockerBackend against a temporary PostgreSQL restored from a copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

from .backend import DockerBackend


def run(args, *, input=None, output=None):
    result = subprocess.run(args, input=input, stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError('ISOLATED_DOCKER_OPERATION_FAILED')
    return result.stdout or b''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or socket.gethostname() != 'racing-test':
        raise SystemExit('Run as root on the isolated racing-test VM only')
    with args.backup.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    size = args.backup.stat().st_size
    if digest != args.backup_sha256 or size <= 0:
        raise SystemExit('APPROVED_BACKUP_HASH_MISMATCH')

    target = json.loads(args.target.read_text())
    nonce = uuid.uuid4().hex[:16]
    network = 'racing-prod-sandbox-' + nonce
    alias = 'racing-prod-sandbox-source'
    container = alias + '-' + nonce
    state = Path(tempfile.mkdtemp(prefix='lab8-prod-backend-', dir='/var/tmp'))
    state.chmod(0o700)
    net_created = db_created = False
    backend = None
    result = {'mode': 'DOCKER_BACKEND_ISOLATED_REHEARSAL', 'status': 'FAIL',
              'production_changed': False, 'source_backup_sha256': digest,
              'source_backup_bytes': size, 'image': args.image, 'sha': args.sha,
              'target_revision': target['revision'], 'target_fingerprint': target['fingerprint']}
    try:
        run(['docker', 'network', 'create', '--internal', network])
        net_created = True
        run(['docker', 'run', '-d', '--name', container, '--hostname', alias,
             '--network', network, '--network-alias', alias,
             '--tmpfs', '/var/lib/postgresql:rw,nosuid,nodev,size=512m',
             '--health-cmd', 'pg_isready -U postgres -d racing_club',
             '--health-interval', '2s', '--health-timeout', '2s', '--health-retries', '45',
             '-e', 'POSTGRES_DB=racing_club', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
             'postgres:18-alpine'])
        db_created = True
        for _ in range(90):
            inspect = json.loads(run(['docker', 'inspect', '-f', '{{json .State.Health.Status}}', container]))
            if inspect == 'healthy':
                break
            time.sleep(1)
        else:
            raise RuntimeError('ISOLATED_POSTGRES_NOT_READY')
        with args.backup.open('rb') as dump:
            run(['docker', 'exec', '-i', container, 'pg_restore', '-U', 'postgres',
                 '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                 '-d', 'racing_club'], input=dump.read())

        request = {'nonce': nonce + '0' * 16, 'sha': args.sha, 'image': args.image,
                   'target_revision': target['revision']}
        settings = {'state_dir': str(state), 'db_container': container,
                    'network': network,
                    'database_url': f'postgresql+psycopg://postgres@{alias}:5432/racing_club'}
        backend = DockerBackend(request, settings, target, sandbox=True)
        original = backend.inspect()
        if original['revision'] != 'legacy' or not original['postgres'].startswith('18.'):
            raise RuntimeError('RESTORED_SOURCE_STATE_MISMATCH')
        backend.quiesce()  # Sandbox mode never stops a host service.
        source_data = backend.data()
        backup = backend.backup()
        if not backup['bytes'] or len(backup['sha256']) != 64:
            raise RuntimeError('BACKEND_BACKUP_INVALID')
        restored = backend.restore(backup)
        if not restored['structure_ok'] or restored['data'] != source_data:
            raise RuntimeError('BACKEND_RESTORE_MISMATCH')
        rehearsal = backend.rehearse(source_data)
        if not rehearsal['schema_ok'] or not rehearsal['data_ok']:
            raise RuntimeError('BACKEND_REHEARSAL_MISMATCH')
        backend.migrate()
        if not backend.verify(source_data):
            raise RuntimeError('BACKEND_POSTCHECK_MISMATCH')
        result.update(status='PASS', postgresql=original['postgres'],
                      source_revision=original['revision'],
                      backup_restore='PASS', migration='PASS',
                      target_schema='PASS', preservation='PASS',
                      backend_backup_bytes=backup['bytes'],
                      backend_backup_sha256=backup['sha256'])
    except Exception as error:
        result['error'] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    finally:
        if backend:
            backend.cleanup()
        if db_created:
            subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        if net_created:
            subprocess.run(['docker', 'network', 'rm', network], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        shutil.rmtree(state, ignore_errors=True)
    print(json.dumps(result, sort_keys=True))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
