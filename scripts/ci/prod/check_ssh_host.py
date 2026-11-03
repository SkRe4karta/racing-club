"""Read-only SSH reachability and host-key pin verification for RACING-CI."""
import json
import os
from pathlib import Path
import subprocess

from .gates import Refused, require

HOST = '10.20.0.13'
PORT = '22'
EXPECTED_FINGERPRINT = 'SHA256:Wd0M13oHDNqf4C2kbbtxAMlq3BJ+nINLR86jM336j14'


def main():
    scanned = subprocess.run(
        ['ssh-keyscan', '-T', '5', '-p', PORT, '-t', 'ed25519', HOST],
        capture_output=True, text=True, check=False,
    )
    lines = [line for line in scanned.stdout.splitlines() if line and not line.startswith('#')]
    require(scanned.returncode == 0 and lines, 'PROD_SSH_PORT_UNREACHABLE')
    pinned = []
    for line in lines:
        fields = line.split()
        require(len(fields) == 3 and fields[0] == HOST and fields[1] == 'ssh-ed25519',
                'UNEXPECTED_PROD_HOST_KEY_FORMAT')
        result = subprocess.run(['ssh-keygen', '-lf', '/dev/stdin'], input=line,
                                capture_output=True, text=True, check=False)
        require(result.returncode == 0, 'INVALID_PROD_HOST_KEY')
        fingerprint = result.stdout.split()[1]
        require(fingerprint == EXPECTED_FINGERPRINT, 'PROD_HOST_FINGERPRINT_MISMATCH')
        pinned.append(line)
    require(len(set(pinned)) == 1, 'PROD_HOST_KEY_CHANGED_DURING_SCAN')

    path = Path(os.environ.get('PROD_KNOWN_HOSTS_FILE', 'artifacts/prod-release/known_hosts'))
    require(path.is_absolute() or '..' not in path.parts, 'INVALID_KNOWN_HOSTS_PATH')
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'KNOWN_HOSTS_PATH_SYMLINK')
    path.write_text('\n'.join(pinned) + '\n')
    path.chmod(0o600)
    print(json.dumps({'host': HOST, 'port': int(PORT), 'status': 'PASS',
                      'fingerprint': EXPECTED_FINGERPRINT,
                      'authentication': 'NOT_ATTEMPTED'}))


if __name__ == '__main__':
    try:
        main()
    except Refused as error:
        print(json.dumps({'host': HOST, 'port': int(PORT), 'status': 'FAIL',
                          'error': str(error)}))
        raise SystemExit(1)
