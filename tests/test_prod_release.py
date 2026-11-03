"""Release safeguards: controlled ports, no network/real accounts or production DB."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from scripts.ci.prod.gates import Refused, execute, provenance, request_hash


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.previous = 0
        self.state = dict(database='racing_club', postgres='18.6', revision='legacy', fingerprint='a' * 64)
        self.original = {'competitions': {'count': 1, 'sha256': 'fixture-hash'}}
        self.fault = None

    def last_build(self):
        return self.previous

    def inspect(self):
        if self.fault == 'schema_drift_after_rehearsal' and 'rehearse' in self.calls:
            return {**self.state, 'fingerprint': 'd' * 64}
        return self.state

    def quiesce(self):
        self.calls.append('quiesce')

    def data(self):
        return self.original

    def backup(self):
        self.calls.append('backup')
        if self.fault == 'backup':
            raise Refused('BACKUP_COMMAND_FAILED')
        return {'bytes': 42, 'sha256': 'b' * 64}

    def restore(self, backup):
        self.calls.append('restore')
        if self.fault == 'restore':
            raise Refused('RESTORE_FAILED')
        return {'data': self.original, 'structure_ok': True}

    def rehearse(self, original):
        self.calls.append('rehearse')
        return {'schema_ok': self.fault != 'rehearse', 'data_ok': True}

    def migrate(self):
        self.calls.append('LIVE_DDL')

    def verify(self, original):
        return True

    def deploy(self):
        self.calls.append('DEPLOY')

    def commit(self, backup):
        self.calls.append('commit')

    def cleanup(self):
        self.calls.append('cleanup')

    def recover_web(self):
        self.calls.append('recover_web')


class ReleaseSafeguardsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.q = dict(sha='1' * 40, image='skre4karta/racing-club@sha256:' + '2' * 64,
                      dev_build=528, stage_build=530, database='racing_club',
                      source_revision='legacy', source_fingerprint='a' * 64,
                      nonce='3' * 32, target_revision='0007_organizer_contact')
        structure = {'tables': {}}
        self.target = dict(revision=self.q['target_revision'], postgres='18.6', structure=structure,
                           fingerprint=hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest())
        self.q['target_fingerprint'] = self.target['fingerprint']
        self.owner = dict(approved=True, owner='test-owner', request_sha256=request_hash(self.q),
                          window_start=(self.now - timedelta(minutes=1)).isoformat(),
                          window_end=(self.now + timedelta(minutes=30)).isoformat(), recovery_plan='controlled-fixture-plan')
        self.backend = FakeBackend()
        self.dev = dict(id=528, buildTypeId='RacingClub_DevVerifyPublish', state='finished', status='SUCCESS',
                        branchName='dev', revisions={'revision': [{'version': self.q['sha']}]})
        self.stage = copy.deepcopy(self.dev)
        self.stage.update(id=530, buildTypeId='RacingClub_StageDeploy')
        self.published = dict(sha=self.q['sha'], image=self.q['image'], build_id='528')

    def check_provenance(self):
        provenance(self.q, self.dev, self.stage, self.published, self.target, [{'id': 528}])

    def refuse(self, code, credentials=True):
        with self.assertRaisesRegex(Refused, code):
            execute(self.q, self.owner, credentials, self.backend, self.now)
        self.assertNotIn('LIVE_DDL', self.backend.calls)
        self.assertNotIn('DEPLOY', self.backend.calls)

    def test_missing_release_approval(self):
        self.owner['approved'] = False
        self.refuse('RELEASE_APPROVAL_REQUIRED')
        self.assertEqual(self.backend.calls, [])

    def test_missing_prod_credentials(self):
        self.refuse('PROD_CREDENTIALS_REQUIRED', credentials=False)
        self.assertEqual(self.backend.calls, [])

    def test_sha_or_digest_mismatch(self):
        self.dev['revisions']['revision'][0]['version'] = '0' * 40
        with self.assertRaisesRegex(Refused, 'SHA_MISMATCH'):
            self.check_provenance()
        self.dev['revisions']['revision'][0]['version'] = self.q['sha']
        self.published['image'] = 'skre4karta/racing-club@sha256:' + '0' * 64
        with self.assertRaisesRegex(Refused, 'DIGEST_MISMATCH'):
            self.check_provenance()
        self.assertEqual(self.backend.calls, [])

    def test_backup_failure_blocks_restore_and_ddl(self):
        self.backend.fault = 'backup'
        self.refuse('BACKUP_COMMAND_FAILED')
        self.assertNotIn('restore', self.backend.calls)
        self.assertIn('recover_web', self.backend.calls)

    def test_restore_failure_blocks_ddl(self):
        self.backend.fault = 'restore'
        self.refuse('RESTORE_FAILED')
        self.assertNotIn('rehearse', self.backend.calls)

    def test_schema_drift(self):
        self.backend.state['fingerprint'] = 'c' * 64
        self.refuse('SCHEMA_DRIFT')
        self.assertEqual(self.backend.calls, [])

    def test_wrong_target_database(self):
        self.backend.state['database'] = 'racing_other'
        self.refuse('WRONG_DATABASE')

    def test_wrong_alembic_revision(self):
        self.backend.state['revision'] = 'unreviewed_migration'
        self.refuse('ALEMBIC_REVISION_MISMATCH')

    def test_older_or_replayed_build(self):
        self.backend.previous = 529
        self.refuse('OLDER_OR_REPLAYED_BUILD')
        self.assertEqual(self.backend.calls, [])

    def test_expired_window(self):
        self.owner['window_end'] = (self.now - timedelta(seconds=1)).isoformat()
        self.refuse('MAINTENANCE_WINDOW_CLOSED')

    def test_rehearsal_failure_blocks_live_ddl(self):
        self.backend.fault = 'rehearse'
        self.refuse('CANDIDATE_REHEARSAL_FAILED')

    def test_schema_drift_after_rehearsal_blocks_live_ddl(self):
        self.backend.fault = 'schema_drift_after_rehearsal'
        self.refuse('SOURCE_SCHEMA_CHANGED_DURING_BACKUP')

    def test_wrong_target_revision_blocks_provenance(self):
        self.q['target_revision'] = '0006_registration_notes'
        with self.assertRaisesRegex(Refused, 'UNREVIEWED_TARGET_REVISION'):
            self.check_provenance()
        self.assertEqual(self.backend.calls, [])

    def test_missing_exact_stage_dependency_blocks_provenance(self):
        with self.assertRaisesRegex(Refused, 'STAGE_DEPENDENCY_MISMATCH'):
            provenance(self.q, self.dev, self.stage, self.published, self.target, [])
        self.assertEqual(self.backend.calls, [])

    def test_success_order_is_backup_restore_rehearsal_before_live_ddl(self):
        self.check_provenance()
        result = execute(self.q, self.owner, True, self.backend, self.now)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(self.backend.calls, ['quiesce', 'backup', 'restore', 'rehearse',
                                             'LIVE_DDL', 'DEPLOY', 'commit', 'cleanup'])
