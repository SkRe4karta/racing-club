#!/usr/bin/env bash
# Native schema-only export from a named disposable TEST container.
set -Eeuo pipefail
container=${1:?Disposable PostgreSQL container required}
database=${2:?Confirmed disposable database required}
output=${3:?Explicit output directory required}
[[ "$container" == racing-ci-pg-* || "$container" == racing-lab8-* ]]
[[ "$database" =~ ^racing_(lab8|test)_[a-z0-9_]+$ ]]
actual=$(docker exec "$container" psql -U postgres -d "$database" -Atc 'SELECT current_database()')
[[ "$actual" == "$database" ]]
version=$(docker exec "$container" pg_dump --version)
[[ "$version" == *'PostgreSQL) 18.'* ]]
revision=$(docker exec "$container" psql -U postgres -d "$database" -Atc 'SELECT version_num FROM alembic_version')
mkdir -p "$output"
raw=$(mktemp)
trap 'rm -f "$raw"' EXIT
docker exec "$container" pg_dump -U postgres --schema-only --no-owner --no-privileges "$database" > "$raw"
python3 "$(dirname "$0")/normalize_ddl.py" < "$raw" > "$output/schema.sql"
python3 - "$output" "$revision" "$version" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path
out, revision, version = sys.argv[1:]
path = Path(out) / 'schema.sql'
metadata = dict(revision=revision, pg_dump_version=version,
                sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                schema_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
(Path(out) / 'export.json').write_text(json.dumps(metadata, indent=2) + '\n')
PY
