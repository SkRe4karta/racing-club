"""Explicit non-destructive demo import. Never reads the application's DATABASE_URL."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import secrets
import sys
from time import perf_counter
from app import create_app, db
from app.demo import DemoError, generate, guard_target, row_counts, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('generate', 'validate', 'counts'))
    parser.add_argument('--size', choices=('small', 'full'), default='full')
    parser.add_argument('--seed', type=int, default=20261016)
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    parser.add_argument('--accounts', type=Path)
    parser.add_argument('--confirm-demo', action='store_true')
    args = parser.parse_args(argv)
    try:
        uri = os.environ.get('RACING_DEMO_DATABASE_URL', '')
        guard_target(uri)
        app = create_app({'SQLALCHEMY_DATABASE_URI': uri, 'SECRET_KEY': secrets.token_hex(32)})
        started = perf_counter()
        with app.app_context():
            if args.command == 'generate':
                if not args.confirm_demo or not args.accounts:
                    raise DemoError('Нужны --confirm-demo и --accounts вне репозитория.')
                report = generate(args.size, args.seed, args.as_of, args.accounts)
            elif args.command == 'validate':
                report = validate()
            else:
                report = {'counts': row_counts()}
            report['seconds'] = round(perf_counter() - started, 3)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            db.session.remove()
            db.engine.dispose()
        return 0
    except DemoError as exc:
        print(f'Отказ: {exc}', file=sys.stderr)
        return 1
    except Exception:
        # SQLAlchemy exceptions may include URI/parameters; don't print credentials.
        print('Отказ: проверьте пустоту, demo-имя БД, миграции, параметры и путь accounts. '
              'Данные не удаляются; безопасные условия описаны в docs/BETA1.md.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
