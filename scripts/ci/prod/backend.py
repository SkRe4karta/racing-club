"""Docker production transaction. Sandbox uses the same operations on owned resources."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit

from .gates import Refused, require
from scripts.ci.compare_schema import differences

TOOLS = Path(__file__).resolve().parents[1]


class DockerBackend:
    def __init__(self, request, settings, target, sandbox=False):
        self.q, self.s, self.target, self.sandbox = request, settings, target, sandbox
        self.work = Path(settings['state_dir']) / ('attempt-' + request['nonce'])
        self.pg = 'racing-prod-copy-' + request['nonce'][:16]
        self.net = self.pg + '-net'
        self.counter = 0
        self.copy_url = f'postgresql+psycopg://postgres@{self.pg}/racing_prod_restore'
        self.base_columns = None
        self.quiesced = False
        self.migration_started = False
        self.pg_created = False
        self.net_created = False
        self.work.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.work.chmod(0o700)
        if sandbox:
            require(settings['db_container'].startswith('racing-prod-sandbox-') and
                    settings['network'].startswith('racing-prod-sandbox-'), 'INVALID_SANDBOX_RESOURCES')
        else:
            require(os.geteuid() == 0 and socket.gethostname() == 'racing-prod', 'WRONG_PRODUCTION_HOST')
            require(settings['db_container'] == 'racing-club-prod-db-1' and
                    settings['web_container'] == 'racing-club-prod-web-1', 'WRONG_PRODUCTION_CONTAINER')
            require(len(settings.get('secret_key', '')) >= 32, 'PERSISTENT_SECRET_KEY_REQUIRED')

    def command(self, args, input=None, output=None, env=None):
        result = subprocess.run(args, input=input, stdout=output or subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, check=False)
        if result.returncode:
            # Never expose argv/env/stderr: they can contain SQL values or credentials.
            with (self.work / 'private-errors.log').open('ab') as log:
                log.write(result.stderr or b'')
            raise Refused('COMMAND_FAILED_' + args[0].replace('/', '_'))
        return result.stdout or b''

    def application(self, args, copy=False, helper=False, columns=None):
        env = os.environ.copy()
        env.update(DATABASE_URL=self.copy_url if copy else self.s['database_url'],
                   EXPECTED_DATABASE_NAME='racing_prod_restore' if copy else 'racing_club',
                   SECRET_KEY=self.s.get('secret_key', 'isolated-rehearsal-only-key'),
                   PRESERVATION_COLUMNS=json.dumps(columns) if columns is not None else 'null')
        flags = ['--network', self.net if copy else self.s['network']]
        for name in ('DATABASE_URL', 'EXPECTED_DATABASE_NAME', 'SECRET_KEY', 'PRESERVATION_COLUMNS'):
            flags += ['-e', name]
        if not helper:
            return self.command(['docker', 'run', '--rm', *flags, self.q['image'], *args], env=env)
        self.counter += 1
        name = self.pg + '-helper-' + str(self.counter)
        helper_created = False
        try:
            self.command(['docker', 'create', '--name', name, *flags, '-e', 'PYTHONPATH=/tmp/release',
                          self.q['image'], 'python', '/tmp/release/' + args[0], *args[1:]], env=env)
            helper_created = True
            self.command(['docker', 'cp', str(TOOLS) + '/.', name + ':/tmp/release'])
            return self.command(['docker', 'start', '-a', name])
        finally:
            if locals().get('helper_created'):
                subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def snapshot(self, copy=False):
        return json.loads(self.application(['prod/db.py', 'snapshot'], copy=copy, helper=True))

    def last_build(self):
        p = Path(self.s['state_dir']) / 'success.json'
        return json.loads(p.read_text())['dev_build'] if p.exists() else 0

    def inspect(self):
        uri = urlsplit(self.s['database_url'])
        require(uri.path == '/racing_club', 'WRONG_DATABASE')
        db = json.loads(self.command(['docker', 'inspect', self.s['db_container']]))[0]
        require(db['Config']['Image'] == 'postgres:18-alpine' and
                db['State'].get('Health', {}).get('Status') == 'healthy', 'PRODUCTION_DB_NOT_HEALTHY')
        network = db['NetworkSettings']['Networks'].get(self.s['network'])
        require(network is not None and uri.hostname in set(network.get('Aliases', [])) | {self.s['db_container']}, 'DATABASE_HOST_NOT_PRODUCTION')
        if not self.sandbox:
            web = json.loads(self.command(['docker', 'inspect', self.s['web_container']]))[0]
            require(web['Config']['Labels'].get('com.docker.compose.project') == 'racing-club-prod', 'WRONG_COMPOSE_PROJECT')
            require(self.s['network'] in web['NetworkSettings']['Networks'], 'WRONG_WEB_NETWORK')
            bindings = [p for values in web['HostConfig']['PortBindings'].values() for p in values]
            require(any(p['HostPort'] == str(self.s['web_port']) and
                        (p.get('HostIp') or '0.0.0.0') == self.s['web_bind'] for p in bindings), 'WEB_PORT_DRIFT')
        self.command(['docker', 'pull', self.q['image']])
        label = self.command(['docker', 'image', 'inspect', '-f', '{{index .Config.Labels "org.opencontainers.image.revision"}}', self.q['image']]).decode().strip()
        require(label == self.q['sha'], 'IMAGE_REVISION_MISMATCH')
        state = self.snapshot()
        (self.work / 'before-schema.json').write_text(json.dumps(state, indent=2))
        return state

    def quiesce(self):
        if not self.sandbox:
            self.command(['docker', 'stop', self.s['web_container']])
        self.quiesced = True

    def data(self, copy=False):
        value = json.loads(self.application(['data-fingerprint.py'], copy=copy, helper=True,
                                            columns=self.base_columns))
        if self.base_columns is None:
            self.base_columns = value['columns']
        return value

    def backup(self):
        size = int(self.command(['docker', 'exec', self.s['db_container'], 'sh', '-c',
                   'exec psql -X -At -U "${POSTGRES_USER:-postgres}" -d racing_club -c "SELECT pg_database_size(current_database())"']))
        require(shutil.disk_usage(self.work).free > max(1024**3, size * 5), 'INSUFFICIENT_BACKUP_SPACE')
        path = self.work / 'before.dump'
        with path.open('xb') as dump:
            path.chmod(0o600)
            self.command(['docker', 'exec', self.s['db_container'], 'sh', '-c',
                          'exec pg_dump -U "${POSTGRES_USER:-postgres}" -Fc racing_club'], output=dump)
        with path.open('rb') as dump:
            digest = hashlib.file_digest(dump, 'sha256').hexdigest()
        return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}

    def restore(self, backup):
        self.command(['docker', 'network', 'create', '--internal', self.net])
        self.net_created = True
        self.command(['docker', 'run', '-d', '--name', self.pg, '--network', self.net,
                      '--tmpfs', '/var/lib/postgresql', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', 'postgres:18-alpine'])
        self.pg_created = True
        ready = False
        for _ in range(90):
            result = subprocess.run(['docker', 'exec', self.pg, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(1)
        require(ready, 'RESTORE_POSTGRES_NOT_READY')
        self.command(['docker', 'exec', self.pg, 'createdb', '-U', 'postgres', 'racing_prod_restore'])
        # Restore private bytes over stdin; never publish the dump as an artifact.
        with open(backup['path'], 'rb') as dump:
            result = subprocess.run(['docker', 'exec', '-i', self.pg, 'pg_restore', '-U', 'postgres',
                                     '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                                     '-d', 'racing_prod_restore'], stdin=dump, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        require(result.returncode == 0, 'RESTORE_FAILED')
        original = json.loads((self.work / 'before-schema.json').read_text())
        restored = self.snapshot(copy=True)
        return {'structure_ok': not differences(restored, original), 'data': self.data(copy=True)}

    def upgrade(self, copy=False):
        current = self.snapshot(copy)['revision']
        if current == 'legacy':
            self.application(['flask', '--app', 'run', 'adopt-legacy'], copy)
        self.application(['flask', '--app', 'run', 'db', 'upgrade', self.q['target_revision']], copy)
        self.application(['flask', '--app', 'run', 'db', 'check'], copy)

    def rehearse(self, original):
        self.upgrade(copy=True)
        return {'schema_ok': not differences(self.snapshot(copy=True), self.target),
                'data_ok': self.data(copy=True) == original}

    def migrate(self):
        self.migration_started = True
        self.upgrade()

    def verify(self, original):
        return not differences(self.snapshot(), self.target) and self.data() == original

    def deploy(self):
        if self.sandbox:
            return  # Docker/DB steps are real; no production web exists in sandbox.
        env = os.environ.copy()
        env.update(RACING_IMAGE=self.q['image'], PROD_DATABASE_URL=self.s['database_url'],
                   SECRET_KEY=self.s['secret_key'], PROD_NETWORK=self.s['network'],
                   PROD_WEB_BIND=self.s['web_bind'], PROD_WEB_PORT=str(self.s['web_port']),
                   SESSION_COOKIE_SECURE=str(self.s['secure_cookie']).lower())
        self.command(['docker', 'compose', '-p', 'racing-club-prod', '-f',
                      str(TOOLS.parents[1] / 'compose.prod-release.yaml'), 'up', '-d', '--no-deps',
                      '--no-build', '--wait', '--wait-timeout', '120', 'web'], env=env)
        label = self.command(['docker', 'inspect', '-f', '{{.Image}}', self.s['web_container']]).strip()
        wanted = self.command(['docker', 'image', 'inspect', '-f', '{{.Id}}', self.q['image']]).strip()
        require(label == wanted, 'DEPLOYED_IMAGE_MISMATCH')

    def commit(self, backup):
        receipt = {'status': 'PASS', 'dev_build': int(self.q['dev_build']), 'sha': self.q['sha'],
                   'image': self.q['image'], 'backup_sha256': backup['sha256'], 'backup_bytes': backup['bytes'],
                   'revision': self.q['target_revision'], 'sandbox': self.sandbox}
        (self.work / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        path = Path(self.s['state_dir']) / 'success.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(receipt, indent=2))
        temporary.replace(path)

    def recover_web(self):
        if self.quiesced and not self.sandbox and not self.migration_started:
            subprocess.run(['docker', 'start', self.s['web_container']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup(self):
        if self.pg_created:
            subprocess.run(['docker', 'rm', '-f', self.pg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.net_created:
            subprocess.run(['docker', 'network', 'rm', self.net], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
