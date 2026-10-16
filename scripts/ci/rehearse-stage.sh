#!/usr/bin/env bash
# Restore/adopt/migrate a new logical copy; never delete an existing database.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/../.."
: "${STAGE_DATABASE_NAME:?Source/target STAGE database identity}"
: "${STAGE_DATABASE_URL:?Source/target URL, never historical racing_club}"
: "${BACKUP_PATH:?Custom-format backup of that database}"
: "${RACING_IMAGE:?Accepted immutable runtime image}"
: "${EXPECTED_SHA:?Full accepted revision}"
: "${DEPLOY_STATE_DIR:?Private persistent state directory}"
: "${REHEARSAL_RECEIPT:?New private output path}"
[[ ! -e "$REHEARSAL_RECEIPT" ]]
[[ "$STAGE_DATABASE_NAME" =~ ^racing_(club_beta1|stage_[a-z0-9_]+|demo_[a-z0-9_]+)$ ]]
[[ "$RACING_IMAGE" =~ ^skre4karta/racing-club@sha256:[a-f0-9]{64}$ && "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ ]]
[[ -s "$BACKUP_PATH" && "$DEPLOY_STATE_DIR" = /* ]]
mkdir -p "$DEPLOY_STATE_DIR"
exec 9>"$DEPLOY_STATE_DIR/deploy.lock"
flock -n 9 || { echo 'Another STAGE operation is running' >&2; exit 1; }
work=$(mktemp -d "$DEPLOY_STATE_DIR/rehearsal.XXXXXXXX")
rehearsal="racing_stage_rehearsal_$(date -u +%Y%m%d%H%M%S)_${RANDOM}"
compose=(docker compose -p racing-club-beta1 --env-file "${STAGE_ENV_FILE:?Private env file}" -f compose.stage.yaml)
"${compose[@]}" config --quiet
docker pull "$RACING_IMAGE"
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RACING_IMAGE")" == "$EXPECTED_SHA" ]]
docker exec -i racing-club-stage-db-1 pg_restore --list < "$BACKUP_PATH" > "$work/restore-list.txt"
docker exec racing-club-stage-db-1 sh -c 'exec createdb -U "$POSTGRES_USER" "$1"' sh "$rehearsal"
docker exec -i racing-club-stage-db-1 sh -c 'exec pg_restore -U "$POSTGRES_USER" --exit-on-error --single-transaction --no-owner --no-acl -d "$1"' sh "$rehearsal" < "$BACKUP_PATH"
rehearsal_url=$(python3 - "$rehearsal" <<'PY'
import os, sys, urllib.parse
print(urllib.parse.urlsplit(os.environ['STAGE_DATABASE_URL'])._replace(path='/' + sys.argv[1]).geturl())
PY
)
candidate=("${compose[@]}" run --rm -T --no-deps -e DATABASE_URL="$rehearsal_url" -e EXPECTED_DATABASE_NAME="$rehearsal" web)
"${candidate[@]}" python - < scripts/ci/schema-state.py > "$work/before.json"
"${compose[@]}" run --rm -T --no-deps -e EXPECTED_DATABASE_NAME="$STAGE_DATABASE_NAME" web python - < scripts/ci/schema-state.py > "$work/source.json"
python3 - "$work/source.json" "$work/before.json" <<'PY'
import json, sys
source, restored = [json.load(open(p)) for p in sys.argv[1:]]
assert source['tables'] == restored['tables'] and source['revision'] == restored['revision'], 'Backup differs from target'
PY
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"] or "legacy")' "$work/before.json")
if [[ "$revision" == legacy ]]; then "${candidate[@]}" flask --app run adopt-legacy; fi
"${candidate[@]}" flask --app run db upgrade
"${candidate[@]}" flask --app run db check
"${candidate[@]}" python - < scripts/ci/schema-state.py > "$work/after.json"
python3 - "$work/source.json" "$work/before.json" "$work/after.json" "$BACKUP_PATH" "$RACING_IMAGE" "$EXPECTED_SHA" "$work/receipt.json" <<'PY'
import hashlib, json, pathlib, sys
source, before, after = [json.load(open(p)) for p in sys.argv[1:4]]
assert before['tables'] == after['tables'], 'Restored sporting data changed'
assert after['revision'] == '0005_predictions' and after['table_count'] == 14
with open(sys.argv[4], 'rb') as backup:
    digest = hashlib.file_digest(backup, 'sha256').hexdigest()
pathlib.Path(sys.argv[7]).write_text(json.dumps(dict(source=source, restored=after,
    backup_sha256=digest, image=sys.argv[5], sha=sys.argv[6]), indent=2) + '\n')
PY
cp "$work/receipt.json" "$REHEARSAL_RECEIPT"
printf 'Rehearsal passed; retained database: %s\nReceipt: %s/receipt.json\n' "$rehearsal" "$work"
