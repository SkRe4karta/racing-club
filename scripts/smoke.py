"""Read-only HTTP smoke. Nonzero exit on unavailable DB, page or wrong version."""
import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--version', default='2.0.0-beta.1')
    args = parser.parse_args()
    for path in ('/health', '/', '/horses/', '/owners/', '/jockeys/', '/competitions/past',
                 '/competitions/future', '/rankings', '/predictions/', '/auth/login'):
        with urllib.request.urlopen(args.url.rstrip('/') + path, timeout=15) as response:
            body = response.read().decode()
            if response.status != 200:
                raise SystemExit(f'Smoke failed: {path}')
            if path == '/health' and json.loads(body).get('status') != 'ok':
                raise SystemExit('Database health failed')
            if path == '/' and args.version not in body:
                raise SystemExit('Unexpected application version')
        print(f'OK {path}')


if __name__ == '__main__':
    main()
