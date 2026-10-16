"""Local contract tests. These never contact Docker, registry, SSH, or a VM."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('racing_smoke', ROOT / 'scripts/smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class Response(io.BytesIO):
    status = 200

    def __init__(self, url, body, content_type):
        super().__init__(body.encode())
        self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = content_type


class CIContracts(unittest.TestCase):
    def run_script(self, name, extra):
        # Minimal environment deliberately excludes user deployment secrets.
        env = dict(PATH=os.environ['PATH'], HOME=os.environ['HOME'], **extra)
        return subprocess.run(['bash', str(ROOT / 'scripts/ci' / name)], env=env,
                              cwd=ROOT, capture_output=True, text=True)

    def test_verify_refuses_wrong_checkout_revision(self):
        result = self.run_script('verify.sh', dict(EXPECTED_SHA='f' * 40))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Checkout differs', result.stderr)

    def test_feature_cannot_publish(self):
        result = self.run_script('publish.sh', dict(TC_BRANCH='feature/example',
            DOCKERHUB_REPOSITORY='skre4karta/racing-club', DOCKERHUB_USER='unused',
            DOCKERHUB_TOKEN='unused', EXPECTED_SHA='f' * 40, BUILD_ID='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Only accepted dev builds', result.stderr)

    def test_stage_refuses_historical_db_prod_and_wrong_project(self):
        base = dict(DEPLOY_ENV='STAGE', COMPOSE_PROJECT_NAME='racing-club-beta1',
            RACING_IMAGE='skre4karta/racing-club@sha256:' + 'a' * 64,
            EXPECTED_SHA='a' * 40, STAGE_DATABASE_NAME='racing_club_beta1',
            BACKUP_PATH='/does-not-exist', REHEARSAL_RECEIPT='/does-not-exist',
            DEPLOY_STATE_DIR='/does-not-exist')
        for field, value in [('DEPLOY_ENV', 'PROD'), ('COMPOSE_PROJECT_NAME', 'racing-stage'),
                             ('STAGE_DATABASE_NAME', 'racing_club')]:
            with self.subTest(field=field):
                self.assertNotEqual(self.run_script('deploy-stage.sh', base | {field: value}).returncode, 0)

    def test_smoke_checks_all_pages_and_health(self):
        visited = []
        def request(url, timeout):
            visited.append(url)
            return Response(url, '{"status":"ok"}' if url.endswith('/health') else '2.0.0-beta.1',
                            'application/json' if url.endswith('/health') else 'text/html')
        with patch.object(smoke.urllib.request, 'urlopen', request), patch('sys.argv', ['smoke', 'http://stage:8081']), patch('sys.stdout', io.StringIO()):
            smoke.main()
        self.assertEqual(len(visited), 10)
        self.assertEqual(len(set(visited)), 10)

    def test_smoke_rejects_redirect_fake_health_and_wrong_version(self):
        for defect in ('redirect', 'content-type', 'health', 'version'):
            def request(url, timeout):
                health = url.endswith('/health')
                return Response('http://stage:8081/auth/login' if defect == 'redirect' else url,
                    json.dumps(dict(status='broken' if defect == 'health' else 'ok')) if health else ('old' if defect == 'version' else '2.0.0-beta.1'),
                    'text/html' if defect == 'content-type' or not health else 'application/json')
            with self.subTest(defect=defect), patch.object(smoke.urllib.request, 'urlopen', request), patch('sys.argv', ['smoke', 'http://stage:8081']), patch('sys.stdout', io.StringIO()):
                with self.assertRaises(SystemExit):
                    smoke.main()

    def test_remote_refuses_missing_pinned_host_key(self):
        result = self.run_script('deploy-remote.sh', dict(EXPECTED_SHA='a' * 40,
            UPSTREAM_BUILD_ID='1', STAGE_KNOWN_HOSTS='/does-not-exist'))
        self.assertNotEqual(result.returncode, 0)

    def test_smoke_propagates_http_failure(self):
        error = urllib.error.HTTPError('http://stage:8081/health', 503, 'Unavailable', {}, None)
        with patch.object(smoke.urllib.request, 'urlopen', side_effect=error), patch('sys.argv', ['smoke', 'http://stage:8081']):
            with self.assertRaises(urllib.error.HTTPError):
                smoke.main()


class DeploymentContracts(unittest.TestCase):
    """Exercise Bash ordering/failure propagation with a fake Docker executable."""
    def setUp(self):
        import shutil
        self.temporary = tempfile.TemporaryDirectory(prefix='racing-cd-contract-')
        self.root = Path(self.temporary.name)
        (self.root / 'scripts/ci').mkdir(parents=True)
        for name in ['deploy-stage.sh', 'schema-state.py']:
            shutil.copy(ROOT / 'scripts/ci' / name, self.root / 'scripts/ci' / name)
        (self.root / 'scripts/smoke.py').write_text('print("FAKE HTTP smoke for orchestration test only")\n')
        (self.root / 'compose.stage.yaml').write_text('# Fake Docker does not interpret this file\n')
        (self.root / 'private.env').write_text('')
        (self.root / 'backup.dump').write_bytes(b'FAKE backup; never restored')
        import hashlib
        state = dict(database='racing_club_beta1', revision=None, table_count=5,
                     tables=dict(owners=dict(count=4, sha256='unchanged')))
        receipt = dict(source=state, sha='a' * 40,
            image='skre4karta/racing-club@sha256:' + 'b' * 64,
            backup_sha256=hashlib.sha256(b'FAKE backup; never restored').hexdigest())
        (self.root / 'receipt.json').write_text(json.dumps(receipt))
        (self.root / 'docker').write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FAKE_ROOT'])
args = sys.argv[1:]
with (root / 'calls.log').open('a') as log:
    log.write(' '.join(args) + '\\n')
if args[0] == 'inspect':
    fmt = args[2]
    print('postgres:18-alpine' if 'Config.Image' in fmt else 'healthy' if 'Health.Status' in fmt else 'racing-club-stage_postgres_data /var/lib/postgresql' if 'Mounts' in fmt else 'sha256:fake-image')
elif args[0] == 'image':
    print('a' * 40 if 'revision' in args[3] else 'sha256:fake-image')
elif args[0] == 'compose':
    if 'run' in args and 'python' in args:
        sys.stdin.read()
        state = json.loads((root / 'receipt.json').read_text())['source']
        if (root / 'migrated').exists():
            state.update(revision='0005_predictions', table_count=14)
        print(json.dumps(state, sort_keys=True))
    elif args[-2:] == ['db', 'upgrade']:
        if os.environ.get('FAKE_FAILURE') == 'migration': sys.exit(7)
        (root / 'migrated').touch()
    elif 'up' in args and os.environ.get('FAKE_FAILURE') == 'health':
        sys.exit(8)
''')
        (self.root / 'docker').chmod(0o700)
        self.env = dict(PATH=str(self.root) + ':' + os.environ['PATH'], HOME=os.environ['HOME'],
            DEPLOY_ENV='STAGE', COMPOSE_PROJECT_NAME='racing-club-beta1', EXPECTED_SHA='a' * 40,
            RACING_IMAGE=receipt['image'], STAGE_DATABASE_NAME='racing_club_beta1',
            BACKUP_PATH=str(self.root / 'backup.dump'), REHEARSAL_RECEIPT=str(self.root / 'receipt.json'),
            DEPLOY_STATE_DIR=str(self.root / 'state'), BUILD_ID='20', FAKE_ROOT=str(self.root),
            STAGE_ENV_FILE=str(self.root / 'private.env'))

    def tearDown(self):
        self.temporary.cleanup()

    def deploy(self):
        return subprocess.run(['bash', str(self.root / 'scripts/ci/deploy-stage.sh')],
            env=self.env, text=True, capture_output=True)

    def test_success_receipt_only_after_migration_and_health(self):
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        success = json.loads((self.root / 'state/success.json').read_text())
        self.assertEqual(success['sha'], 'a' * 40)
        self.assertEqual(success['revision'], '0005_predictions')
        calls = (self.root / 'calls.log').read_text()
        self.assertLess(calls.index('adopt-legacy'), calls.index('db upgrade'))
        self.assertLess(calls.index('db upgrade'), calls.index('up -d'))
        self.assertNotIn(' down ', calls)

    def test_migration_failure_stops_before_start_and_no_success(self):
        self.env['FAKE_FAILURE'] = 'migration'
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('up -d', (self.root / 'calls.log').read_text())
        self.assertFalse((self.root / 'state/success.json').exists())

    def test_health_failure_does_not_record_success(self):
        self.env['FAKE_FAILURE'] = 'health'
        self.assertNotEqual(self.deploy().returncode, 0)
        self.assertFalse((self.root / 'state/success.json').exists())

    def test_stale_build_rejected_before_docker(self):
        (self.root / 'state').mkdir()
        (self.root / 'state/success.json').write_text('{"build_id":"21"}')
        self.assertNotEqual(self.deploy().returncode, 0)
        self.assertFalse((self.root / 'calls.log').exists())


if __name__ == '__main__':
    unittest.main()
