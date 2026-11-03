"""Fail closed on structural drift. Row counts are not schema equivalence."""
import argparse
import json
from pathlib import Path


def differences(actual, expected):
    issues = []
    if actual['revision'] != expected['revision']:
        issues.append('Alembic revision differs')
    if not actual['postgres'].startswith('18.'):
        issues.append('PostgreSQL18 required')
    if actual['structure'] != expected['structure']:
        a, e = actual['structure'], expected['structure']
        for section in sorted(set(a) | set(e)):
            if a.get(section) != e.get(section):
                issues.append(f'Structure differs: {section}')
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--actual', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    issues = differences(json.loads(args.actual.read_text()), json.loads(args.expected.read_text()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(dict(result='FAIL' if issues else 'PASS', differences=issues), indent=2) + '\n')
    print('Schema comparison:', 'FAIL' if issues else 'PASS')
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
