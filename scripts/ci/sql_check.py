"""PostgreSQL AST security policy. Never executes SQL or database connections."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from pglast.parser import parse_sql_json


def function_fingerprint(node):
    """Hash full function definition, excluding only parser source positions."""
    def canonical(value):
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()
                    if key not in {'location', 'stmt_location', 'stmt_len'}}
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(canonical(node), sort_keys=True).encode()).hexdigest()


def findings(sql, allowed_functions=()):
    # pg_dump18 emits psql safety guards. Keep them in the export, ignore only
    # these exact guards in the parser; arbitrary psql commands are rejected.
    sql = '\n'.join(line for line in sql.splitlines()
                    if not re.fullmatch(r'\\(?:un)?restrict [A-Za-z0-9]+', line))
    tree = json.loads(parse_sql_json(sql))
    errors = []

    def walk(value):
        if isinstance(value, dict):
            for kind, node in value.items():
                if kind == 'CreateFunctionStmt' and function_fingerprint(node) in allowed_functions:
                    continue
                if kind in {'DropStmt', 'DropdbStmt', 'TruncateStmt', 'CreateRoleStmt',
                            'AlterRoleStmt', 'GrantRoleStmt', 'DoStmt', 'CreateFunctionStmt'}:
                    errors.append(f'CRITICAL: unreviewed destructive/privileged/procedural SQL ({kind})')
                if kind in {'DeleteStmt', 'UpdateStmt'} and not node.get('whereClause'):
                    errors.append(f'CRITICAL: unbounded mutation ({kind})')
                if kind == 'CopyStmt' and node.get('is_program'):
                    errors.append('CRITICAL: COPY PROGRAM')
                if kind == 'GrantStmt' and any('ROLESPEC_PUBLIC' in str(r) for r in node.get('grantees', [])):
                    errors.append('CRITICAL: grants to PUBLIC')
                walk(node)
        elif isinstance(value, list):
            for node in value:
                walk(node)
    walk(tree)
    return sorted(set(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard', '--', '*.sql'], cwd=root).decode().split('\0')
    # Policy travels with the reviewed scanner, never from the scanned checkout.
    policy = Path(__file__).resolve().parents[2] / 'database/sql-policy-exceptions.json'
    allowed_functions = json.loads(policy.read_text())['reviewed_function_ast_sha256']
    reports = []
    for name in sorted(set(filter(None, names))):
        data = (root / name).read_bytes()
        try:
            errors = findings(data.decode('utf-8'), allowed_functions)
        except Exception as error:
            errors = [f'ERROR: parser failed ({type(error).__name__})']
        reports.append({'file': name, 'sha256': hashlib.sha256(data).hexdigest(), 'findings': errors})
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    failed = any(row['findings'] for row in reports)
    result = dict(sha=sha, tool='pglast 8.7 + project AST policy', result='FAIL' if failed else 'PASS',
                  files=reports, scope_count=len(reports))
    out = root / 'artifacts/sql-analysis/report.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'SQL analysis {result["result"]}: {len(reports)} files; SHA {sha}')
    for row in reports:
        for message in row['findings']:
            print(row['file'] + ': ' + message)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
