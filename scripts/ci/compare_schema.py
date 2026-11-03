"""Fail closed on structural drift. Row counts are not schema equivalence."""
import argparse
import copy
import re
import json
from pathlib import Path


def canonical_structure(structure):
    """Normalize one PG dump/restore rewrite of literal varchar arrays.

    PostgreSQL can move the text[] cast onto each varchar literal during restore.
    No casts on columns, operators, values or predicates are discarded.
    """
    result = copy.deepcopy(structure)
    literal = r"'(?:[^']|'')*'::character varying"
    patterns = [re.compile(r"ARRAY\[(" + literal + r"(?:, " + literal + r")*)\]::text\[\]"),
                re.compile(r"\(ARRAY\[(" + literal + r"(?:, " + literal + r")*)\]\)::text\[\]")]

    def expression(text):
        for pattern in patterns:
            text = pattern.sub(
                lambda match: 'ARRAY[' + re.sub(literal, lambda item: item[0] + '::text', match[1]) + ']', text)
        return re.sub(r"\((" + literal + r")\)::text", r"\1::text", text)

    for table in result['tables'].values():
        for check in table.get('checks', []):
            check['sqltext'] = expression(check['sqltext'])
        for index in table.get('indexes', []):
            options = index.get('dialect_options', {})
            if 'postgresql_where' in options:
                options['postgresql_where'] = expression(options['postgresql_where'])
    return result


def differences(actual, expected):
    issues = []
    if actual['revision'] != expected['revision']:
        issues.append('Alembic revision differs')
    if not actual['postgres'].startswith('18.'):
        issues.append('PostgreSQL18 required')
    a, e = [canonical_structure(item['structure']) for item in (actual, expected)]
    if a != e:
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
