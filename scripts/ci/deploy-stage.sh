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
: "${DEPLOY_STATE_DIR:?Persistent private directory outside the release checkout}"
[[ "$DEPLOY_ENV" == STAGE && "$COMPOSE_PROJECT_NAME" == racing-club-beta1 ]]
[[ "$RACING_IMAGE" =~ ^skre4karta/racing-club@sha256:[a-f0-9]{64}$ ]]
[[ "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ ]]
[[ "$STAGE_DATABASE_NAME" =~ ^racing_(club_beta1|stage_[a-z0-9_]+|demo_[a-z0-9_]+)$ ]]
[[ "$DEPLOY_STATE_DIR" = /* ]]
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
# The lab database is already migrated. Inspect the target image's migration head.
head=$("${compose[@]}" run --rm -T --no-deps web python -c 'from alembic.config import Config; from alembic.script import ScriptDirectory; c=Config(); c.set_main_option("script_location", "migrations"); print(ScriptDirectory.from_config(c).get_current_head())')
revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"] or "legacy")' "$work/before.json")
[[ "$head" =~ ^[a-zA-Z0-9_]+$ ]]
# Retain the prior image for a compatible web-only rollback.
docker inspect --format '{{.Image}}' racing-club-beta1-web-1 > "$work/previous-image-id.txt"
if [[ "$revision" != "$head" ]]; then
  # Legacy adoption was completed separately; never infer it on an active database.
  [[ "$revision" != legacy ]] || { echo 'Legacy database requires explicit adoption outside CD' >&2; exit 1; }
  "${compose[@]}" stop web
  schema_state > "$work/stopped.json"
  cmp "$work/before.json" "$work/stopped.json"
  export BACKUP_PATH="$work/before.dump" REHEARSAL_RECEIPT="$work/receipt.json"
  docker exec racing-club-stage-db-1 sh -c 'exec pg_dump -U "$POSTGRES_USER" -Fc "$1"' sh "$STAGE_DATABASE_NAME" > "$BACKUP_PATH"
  bash scripts/ci/rehearse-stage.sh
  "${compose[@]}" run --rm -T --no-deps web flask --app run db upgrade
  "${compose[@]}" run --rm -T --no-deps web flask --app run db check
  schema_state > "$work/after.json"
  python3 - "$work/before.json" "$work/after.json" "$head" <<'CHECK'
import json, sys
before, after = [json.load(open(p)) for p in sys.argv[1:3]]
assert before['tables'] == after['tables'], 'Sporting data changed during migration'
assert after['revision'] == sys.argv[3], 'Migration did not reach image head'
CHECK
else
  # No schema changes: no backup, rehearsal database, adopt-legacy or upgrade.
  cp "$work/before.json" "$work/after.json"
  echo "Database already at image migration head: $head"
fi
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
