#!/usr/bin/env bash
# Execute ON STAGE. Only the Beta project is updated; old web/db stay intact.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/../.."
: "${DEPLOY_ENV:?Must be STAGE}"
: "${COMPOSE_PROJECT_NAME:?Must be racing-club-beta1}"
: "${RACING_IMAGE:?Use repository@sha256:digest}"
: "${EXPECTED_SHA:?Full successful dev revision}"
: "${STAGE_DATABASE_NAME:?Explicit separately migrated database}"
: "${BACKUP_PATH:?Backup of the target database}"
: "${REHEARSAL_RECEIPT:?Successful rehearsal receipt for this image and backup}"
: "${DEPLOY_STATE_DIR:?Persistent private directory outside the release checkout}"
[[ "$DEPLOY_ENV" == STAGE && "$COMPOSE_PROJECT_NAME" == racing-club-beta1 ]]
[[ "$RACING_IMAGE" =~ ^skre4karta/racing-club@sha256:[a-f0-9]{64}$ ]]
[[ "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ ]]
[[ "$STAGE_DATABASE_NAME" =~ ^racing_(club_beta1|stage_[a-z0-9_]+|demo_[a-z0-9_]+)$ ]]
[[ -s "$BACKUP_PATH" && -s "$REHEARSAL_RECEIPT" && "$DEPLOY_STATE_DIR" = /* ]]
mkdir -p "$DEPLOY_STATE_DIR"
exec 9>"$DEPLOY_STATE_DIR/deploy.lock"
flock -n 9 || { echo 'Another STAGE operation is running' >&2; exit 1; }
: "${BUILD_ID:?Successful upstream TeamCity build.id}"
[[ "$BUILD_ID" =~ ^[0-9]{1,15}$ && "$BUILD_ID" != 0 ]]
if [[ -f "$DEPLOY_STATE_DIR/success.json" ]]; then
  python3 - "$DEPLOY_STATE_DIR/success.json" "$BUILD_ID" <<'PY'
import json, sys
previous = int(json.load(open(sys.argv[1]))['build_id'])
if int(sys.argv[2]) < previous:
    raise SystemExit('Refusing an older build after a newer successful deployment')
PY
fi
compose=(docker compose -p "$COMPOSE_PROJECT_NAME" --env-file "${STAGE_ENV_FILE:?Private STAGE env file}" -f compose.stage.yaml)
"${compose[@]}" config --quiet
# Fail on infrastructure differences. Never create or replace PostgreSQL here.
[[ "$(docker inspect --format '{{.Config.Image}}' racing-club-stage-db-1)" == postgres:18-alpine ]]
[[ "$(docker inspect --format '{{.State.Health.Status}}' racing-club-stage-db-1)" == healthy ]]
docker inspect --format '{{range .Mounts}}{{println .Name .Destination}}{{end}}' racing-club-stage-db-1 |
  grep -Fxq 'racing-club-stage_postgres_data /var/lib/postgresql'
"${compose[@]}" pull web
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RACING_IMAGE")" == "$EXPECTED_SHA" ]]
work=$(mktemp -d "$DEPLOY_STATE_DIR/attempt.XXXXXXXX")
trap 'echo "STAGE deployment FAILED; private evidence: $work. No automatic DB downgrade." >&2' ERR
schema_state() {
  "${compose[@]}" run --rm -T --no-deps -e EXPECTED_DATABASE_NAME="$STAGE_DATABASE_NAME" web python - < scripts/ci/schema-state.py
}
schema_state > "$work/before.json"
python3 - "$REHEARSAL_RECEIPT" "$work/before.json" "$BACKUP_PATH" "$RACING_IMAGE" "$EXPECTED_SHA" <<'PY'
import hashlib, json, sys
receipt, before = [json.load(open(p)) for p in sys.argv[1:3]]
with open(sys.argv[3], 'rb') as backup:
    digest = hashlib.file_digest(backup, 'sha256').hexdigest()
assert receipt['backup_sha256'] == digest, 'Backup differs from rehearsal'
assert receipt['image'] == sys.argv[4] and receipt['sha'] == sys.argv[5], 'Rehearsal image differs'
assert receipt['source'] == before, 'Database changed after backup/rehearsal'
PY
# Retain the previous Beta image ID for compatible web-only rollback.
docker inspect --format '{{.Image}}' racing-club-beta1-web-1 > "$work/previous-image-id.txt"
"${compose[@]}" stop web
schema_state > "$work/stopped.json"
cmp "$work/before.json" "$work/stopped.json"
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"] or "legacy")' "$work/before.json")
if [[ "$revision" == legacy ]]; then
  "${compose[@]}" run --rm -T --no-deps web flask --app run adopt-legacy
fi
"${compose[@]}" run --rm -T --no-deps web flask --app run db upgrade
"${compose[@]}" run --rm -T --no-deps web flask --app run db check
schema_state > "$work/after.json"
python3 - "$work/before.json" "$work/after.json" <<'PY'
import json, sys
before, after = [json.load(open(p)) for p in sys.argv[1:]]
assert before['tables'] == after['tables'], 'Sporting data changed during migration'
assert after['revision'] == '0005_predictions' and after['table_count'] == 14
PY
"${compose[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 web
[[ "$(docker inspect --format '{{.Image}}' racing-club-beta1-web-1)" == "$(docker image inspect --format '{{.Id}}' "$RACING_IMAGE")" ]]
python3 scripts/smoke.py "http://127.0.0.1:${WEB_PORT:-8081}"
python3 - "$work/after.json" "$RACING_IMAGE" "$EXPECTED_SHA" "$BUILD_ID" "$work/success.json" <<'PY'
import json, pathlib, sys
state = json.load(open(sys.argv[1]))
state.update(image=sys.argv[2], sha=sys.argv[3], build_id=sys.argv[4])
pathlib.Path(sys.argv[5]).write_text(json.dumps(state, indent=2) + '\n')
PY
cp "$work/success.json" "$DEPLOY_STATE_DIR/success.json.new"
mv "$DEPLOY_STATE_DIR/success.json.new" "$DEPLOY_STATE_DIR/success.json"
cat "$work/success.json"
