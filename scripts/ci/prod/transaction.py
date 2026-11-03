"""Install as root-owned fixed entrypoint; never run from an uploaded release bundle."""
import fcntl
import json
import os
from pathlib import Path
import sys

from .backend import DockerBackend
from .gates import Refused, approval, execute, require
import hashlib
from .runner import protected_json


def main():
    backend = None
    try:
        require(os.geteuid() == 0, 'ROOT_WRAPPER_REQUIRED')
        payload = json.load(sys.stdin)
        request = payload['request']
        owner = protected_json(Path('/etc/racing-club/prod-release-approval.json'))
        approval(request, owner)
        target = payload['target']
        require(hashlib.sha256(json.dumps(target['structure'], sort_keys=True, default=list).encode()).hexdigest() == request['target_fingerprint']
                and target['fingerprint'] == request['target_fingerprint']
                and target['revision'] == request['target_revision'], 'TARGET_FINGERPRINT_MISMATCH')
        settings = protected_json(Path('/etc/racing-club/prod-release.json'))
        state = Path(settings['state_dir'])
        require(state.is_absolute() and not state.is_symlink(), 'PRIVATE_STATE_DIRECTORY_REQUIRED')
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        state.chmod(0o700)
        with (state / 'release.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            backend = DockerBackend(request, settings, payload['target'])
            execute(request, owner, True, backend)
            # The target structure is owner-bound too, not caller-controlled authority.
            receipt = json.loads((state / 'success.json').read_text())
            print(json.dumps(receipt))
        return 0
    except Exception as error:
        if backend:
            backend.cleanup()
        print(json.dumps({'status': 'FAIL', 'production_changed': bool(backend and backend.migration_started),
                          'error': str(error) if isinstance(error, Refused) else type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
