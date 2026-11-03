"""TeamCity entrypoint. Check mode never acquires SSH or contacts PROD."""
import argparse
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
from urllib.request import Request, urlopen

from .gates import Refused, provenance, require

KNOWN_HOSTS = Path('/data/teamcity_agent/conf/racing-prod-known-hosts')
PROD_HOST = '10.20.0.13'
PROD_USER = 'zelyonka'


def protected_json(path):
    require(path.exists(), 'PRIVATE_APPROVAL_OR_PROFILE_MISSING')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == 0
            and stat.S_IMODE(info.st_mode) == 0o600, 'PRIVATE_ROOT_FILE_REQUIRED')
    return json.loads(path.read_text())


def api(path):
    token = os.environ.get('TC_BEARER_TOKEN')
    token_path = os.environ.get('TC_TOKEN_FILE')
    if not token and token_path:
        token = Path(token_path).read_text().strip()
    if token:
        authorization = 'Bearer ' + token
    else:
        user, password = os.environ.get('TC_AUTH_USER'), os.environ.get('TC_AUTH_PASSWORD')
        require(bool(user and password), 'TEAMCITY_READ_CREDENTIALS_REQUIRED')
        authorization = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
    req = Request(os.environ.get('TC_URL', 'http://10.20.0.14:8111') + '/app/rest/' + path,
                  headers={'Authorization': authorization, 'Accept': 'application/json'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def collect(request):
    dev = api(f'builds/id:{int(request["dev_build"])}')
    stage = api(f'builds/id:{int(request["stage_build"])}')
    published = api(f'builds/id:{int(request["dev_build"])}/artifacts/content/published-image.json')
    target = api(f'builds/id:{int(request["dev_build"])}/artifacts/content/schema/structure.json')
    provenance(request, dev, stage, published, target, stage.get('snapshot-dependencies', {}).get('build', []))
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('check', 'release'), default='check')
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    out = Path('artifacts/prod-release')
    out.mkdir(parents=True, exist_ok=True)
    record = {'mode': args.mode, 'production_changed': False, 'status': 'FAIL'}
    try:
        q = json.loads(args.request.read_text())
        target = collect(q)
        record.update(sha=q['sha'], image=q['image'], dev_build=q['dev_build'], stage_build=q['stage_build'])
        if args.mode == 'check':
            record.update(status='PASS', provenance='PASS', release_authorized=False,
                          approval_status='NOT_CHECKED', prod_credentials_status='NOT_ACQUIRED',
                          live_database='NOT_CONTACTED')
        else:
            # Owner approval and target settings are root-owned on PROD. The CI
            # identity can invoke only that VM's fixed, root-owned transaction wrapper.
            fingerprint = os.environ.get('PROD_SSH_KEY_FINGERPRINT', '')
            require(bool(fingerprint), 'DEDICATED_PROD_IDENTITY_REQUIRED')
            require(KNOWN_HOSTS.is_file() and not KNOWN_HOSTS.is_symlink(), 'TRUSTED_PROD_HOST_KEY_REQUIRED')
            keys = subprocess.run(['ssh-add', '-l'], capture_output=True, text=True, check=False)
            require(keys.returncode == 0 and fingerprint in keys.stdout, 'PROD_CREDENTIALS_REQUIRED')
            opts = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o',
                    'UserKnownHostsFile=' + str(KNOWN_HOSTS), '-o', 'ConnectTimeout=8']
            # Fixed root-owned wrapper. JSON is stdin, never shell interpolation.
            payload = json.dumps({'request': q, 'target': target}).encode()
            record['production_changed'] = 'UNKNOWN_AFTER_REMOTE_START'
            result = subprocess.run(['ssh', *opts, f'{PROD_USER}@{PROD_HOST}',
                                     'sudo -n /usr/local/sbin/racing-prod-release'], input=payload,
                                    capture_output=True, check=False)
            receipt = json.loads(result.stdout)
            if result.returncode != 0:
                record['production_changed'] = receipt.get('production_changed', 'UNKNOWN_AFTER_REMOTE_START')
                raise Refused('REMOTE_RELEASE_REFUSED_OR_FAILED')
            require(receipt.get('status') == 'PASS' and receipt.get('sha') == q['sha'] and
                    receipt.get('image') == q['image'], 'INVALID_REMOTE_RECEIPT')
            record.update(status='PASS', production_changed=True, remote_receipt=receipt)
        return 0
    except Exception as error:
        record['error'] = str(error) if isinstance(error, Refused) else type(error).__name__
        return 1
    finally:
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record))


if __name__ == '__main__':
    raise SystemExit(main())
