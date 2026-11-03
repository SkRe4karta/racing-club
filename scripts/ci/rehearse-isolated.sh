#!/usr/bin/env bash
# PROD pipeline rehearsal ONLY: isolated Docker PostgreSQL, synthetic records.
# This script has no SSH, registry publish, production URL or deployment path.
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
: "${VERIFIED_IMAGE_SHA:?SHA of a successful FEATURE runtime image}"
[[ "$VERIFIED_IMAGE_SHA" =~ ^[a-f0-9]{40}$ ]]
image="racing-verified:2.0.0-${VERIFIED_IMAGE_SHA:0:12}"
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" == "$VERIFIED_IMAGE_SHA" ]]
pg="racing-lab8-prod-rehearsal-$$"
net="$pg-net"
work=$(mktemp -d)
cleanup() { docker rm -f "$pg" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
umask 077
out=artifacts/prod-rehearsal
mkdir -p "$out"
docker network create --internal "$net" >/dev/null
docker run -d --name "$pg" --network "$net" --tmpfs /var/lib/postgresql -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18-alpine >/dev/null
for i in {1..40}; do docker exec "$pg" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
for name in source restored expected; do docker exec "$pg" createdb -U postgres "racing_lab8_$name"; done
export DATABASE_URL="postgresql+psycopg://postgres@$pg/racing_lab8_source"
export EXPECTED_DATABASE_NAME=racing_lab8_source
app=(docker run --rm -i --network "$net" -e DATABASE_URL -e EXPECTED_DATABASE_NAME -e PRESERVATION_COLUMNS -e SECRET_KEY=isolated-rehearsal "$image")
target_revision=$("${app[@]}" python -c 'from alembic.config import Config; from alembic.script import ScriptDirectory; c=Config(); c.set_main_option("script_location","migrations"); print(ScriptDirectory.from_config(c).get_current_head())')
[[ "$target_revision" =~ ^[a-zA-Z0-9_]+$ ]]
"${app[@]}" flask --app run db upgrade 0001_v11_baseline
docker exec "$pg" psql -X -v ON_ERROR_STOP=1 -U postgres -d racing_lab8_source -c "INSERT INTO competitions (id,title,event_date,event_time,location,status) VALUES (1,'Controlled rehearsal fixture','2026-12-01','12:00','Test','planned')"
"${app[@]}" python - < scripts/ci/data-fingerprint.py > "$out/source-data.json"
docker exec "$pg" pg_dump -U postgres -Fc racing_lab8_source > "$work/source.dump"
docker exec -i "$pg" pg_restore --list < "$work/source.dump" > "$work/restore-list.txt"
docker exec -i "$pg" pg_restore -U postgres --exit-on-error --single-transaction --no-owner --no-acl -d racing_lab8_restored < "$work/source.dump"
export DATABASE_URL="postgresql+psycopg://postgres@$pg/racing_lab8_restored" EXPECTED_DATABASE_NAME=racing_lab8_restored
"${app[@]}" python - < scripts/ci/data-fingerprint.py > "$out/restored-data.json"
cmp "$out/source-data.json" "$out/restored-data.json"
export PRESERVATION_COLUMNS
PRESERVATION_COLUMNS=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["columns"]))' "$out/source-data.json")
"${app[@]}" flask --app run db upgrade "$target_revision"
"${app[@]}" flask --app run db check
"${app[@]}" python - < scripts/ci/data-fingerprint.py > "$out/migrated-data.json"
cmp "$out/source-data.json" "$out/migrated-data.json"
"${app[@]}" python - --expected-db racing_lab8_restored < scripts/ci/schema_snapshot.py > "$out/restored-schema.json"
export DATABASE_URL="postgresql+psycopg://postgres@$pg/racing_lab8_expected" EXPECTED_DATABASE_NAME=racing_lab8_expected
"${app[@]}" flask --app run db upgrade "$target_revision"
"${app[@]}" python - --expected-db racing_lab8_expected < scripts/ci/schema_snapshot.py > "$out/expected-schema.json"
python3 scripts/ci/compare_schema.py --actual "$out/restored-schema.json" --expected "$out/expected-schema.json" --report "$out/comparison.json"
sha256sum "$work/source.dump" | cut -d ' ' -f 1 > "$out/synthetic-backup.sha256"
python3 - "$VERIFIED_IMAGE_SHA" "$target_revision" <<'PY'
import json,subprocess,sys
from pathlib import Path
Path('artifacts/prod-rehearsal/receipt.json').write_text(json.dumps({
 'result':'PASS','mode':'ISOLATED_SYNTHETIC_REHEARSAL','production_changed':False,
 'tools_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'verified_image_sha':sys.argv[1],'source_revision':'0001_v11_baseline',
 'target_revision':sys.argv[2],'backup_restore':'PASS',
 'frozen_columns_all_tables':'PASS','target_schema':'PASS'},indent=2)+'\n')
PY
cat "$out/receipt.json"
