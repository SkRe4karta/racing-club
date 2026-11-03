"""Fail-closed release policy, independent of Docker/SSH implementations."""
import hashlib
import json
import re
from datetime import datetime, timezone


class Refused(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def request_hash(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def approval(request, record, now=None):
    now = now or datetime.now(timezone.utc)
    require(record.get('approved') is True and bool(record.get('owner')), 'RELEASE_APPROVAL_REQUIRED')
    require(record.get('request_sha256') == request_hash(request), 'APPROVAL_REQUEST_MISMATCH')
    try:
        begin, end = [datetime.fromisoformat(record[k]) for k in ('window_start', 'window_end')]
        require(begin.tzinfo is not None and end.tzinfo is not None, 'WINDOW_TIMEZONE_REQUIRED')
        require(begin <= now < end, 'MAINTENANCE_WINDOW_CLOSED')
    except (KeyError, ValueError, TypeError) as error:
        raise Refused('INVALID_MAINTENANCE_WINDOW') from error
    require(bool(record.get('recovery_plan')), 'RECOVERY_PLAN_REQUIRED')


def provenance(request, dev, stage, published, target, dependencies):
    require(re.fullmatch(r'[0-9a-f]{40}', request.get('sha', '')), 'INVALID_SHA')
    require(re.fullmatch(r'skre4karta/racing-club@sha256:[0-9a-f]{64}', request.get('image', '')), 'INVALID_DIGEST')
    require(type(request.get('dev_build')) is int and request['dev_build'] > 0 and
            type(request.get('stage_build')) is int and request['stage_build'] > 0, 'INVALID_BUILD_ID')
    require(request.get('target_fingerprint') == target.get('fingerprint') and
            hashlib.sha256(json.dumps(target['structure'], sort_keys=True, default=list).encode()).hexdigest() == target.get('fingerprint'), 'TARGET_FINGERPRINT_MISMATCH')
    require(request.get('database') == 'racing_club', 'WRONG_DATABASE')
    require(request.get('target_revision') == '0007_organizer_contact', 'UNREVIEWED_TARGET_REVISION')
    require(re.fullmatch(r'[0-9a-f]{32}', request.get('nonce', '')), 'INVALID_NONCE')
    for build, kind, identifier in ((dev, 'RacingClub_DevVerifyPublish', request['dev_build']),
                                    (stage, 'RacingClub_StageDeploy', request['stage_build'])):
        require(build.get('state') == 'finished' and build.get('status') == 'SUCCESS', 'UPSTREAM_NOT_SUCCESS')
        require(str(build.get('id')) == str(identifier), 'UPSTREAM_ID_MISMATCH')
        require(build.get('buildTypeId', build.get('buildType', {}).get('id')) == kind, 'UPSTREAM_CONFIGURATION_MISMATCH')
        require(build.get('branchName') == 'dev', 'UPSTREAM_BRANCH_MISMATCH')
        versions = [r['version'] for r in build.get('revisions', {}).get('revision', [])]
        require(versions == [request['sha']], 'SHA_MISMATCH')
    require(str(request['dev_build']) in {str(b['id']) for b in dependencies}, 'STAGE_DEPENDENCY_MISMATCH')
    require(published.get('sha') == request['sha'] and published.get('image') == request['image'], 'DIGEST_MISMATCH')
    require(str(published.get('build_id')) == str(request['dev_build']), 'PUBLISH_BUILD_MISMATCH')
    require(target.get('revision') == request['target_revision'] and target.get('postgres', '').startswith('18.'), 'TARGET_SCHEMA_MISMATCH')


def execute(request, owner_approval, credentials, backend, now=None):
    """Every mutating operation lives behind policy, fresh backup and restore proof."""
    approval(request, owner_approval, now)
    require(credentials is True, 'PROD_CREDENTIALS_REQUIRED')
    require(int(request['dev_build']) > int(backend.last_build()), 'OLDER_OR_REPLAYED_BUILD')
    before = backend.inspect()
    require(before['database'] == 'racing_club', 'WRONG_DATABASE')
    require(before['revision'] == request['source_revision'], 'ALEMBIC_REVISION_MISMATCH')
    require(before['revision'] in ('legacy', '0005_predictions', '0006_registration_notes', '0007_organizer_contact'), 'UNKNOWN_MIGRATION_HISTORY')
    require(before['fingerprint'] == request['source_fingerprint'], 'SCHEMA_DRIFT')
    require(before.get('postgres', '').startswith('18.'), 'POSTGRES18_REQUIRED')
    stopped = False
    try:
        backend.quiesce()
        stopped = True
        original = backend.data()
        backup = backend.backup()
        require(backup.get('bytes', 0) > 0 and re.fullmatch(r'[0-9a-f]{64}', backup.get('sha256', '')), 'BACKUP_INVALID')
        restored = backend.restore(backup)
        require(restored['data'] == original, 'RESTORED_DATA_MISMATCH')
        require(restored['structure_ok'] is True, 'RESTORED_SCHEMA_MISMATCH')
        proof = backend.rehearse(original)
        require(proof.get('schema_ok') is True and proof.get('data_ok') is True, 'CANDIDATE_REHEARSAL_FAILED')
        approval(request, owner_approval, now)
        current = backend.inspect()
        require(current.get('database') == before['database'] and
                current.get('revision') == before['revision'] and
                current.get('fingerprint') == before['fingerprint'] and
                current.get('postgres') == before['postgres'], 'SOURCE_SCHEMA_CHANGED_DURING_BACKUP')
        require(backend.data() == original, 'SOURCE_CHANGED_DURING_BACKUP')
        backend.migrate()
        require(backend.verify(original) is True, 'LIVE_POSTCHECK_FAILED')
        backend.deploy()
        backend.commit(backup)
        return {'status': 'PASS', 'request_sha256': request_hash(request), 'backup_sha256': backup['sha256']}
    except Exception:
        if stopped:
            backend.recover_web()
        raise
    finally:
        backend.cleanup()
