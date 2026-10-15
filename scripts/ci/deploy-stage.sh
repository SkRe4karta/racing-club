#!/usr/bin/env bash
# Execute locally ON STAGE only after explicit approval and backup rehearsal.
set -Eeuo pipefail
trap 'echo "STAGE deployment failed at line $LINENO; inspect the failed step before recovery." >&2' ERR
cd "$(dirname "$0")/../.."
: "${DEPLOY_ENV:?Must be STAGE}"
: "${COMPOSE_PROJECT_NAME:?Use the existing stage project name}"
: "${RACING_IMAGE:?Use repository@sha256:digest}"
: "${EXPECTED_SHA:?Full accepted dev commit}"
: "${BACKUP_PATH:?Existing checked pre-deployment backup outside repository}"
[[ "$DEPLOY_ENV" == STAGE && "$COMPOSE_PROJECT_NAME" == racing-stage ]]
[[ "$RACING_IMAGE" =~ @sha256:[a-f0-9]{64}$ ]]
[[ "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ ]]
[[ -s "$BACKUP_PATH" ]]
docker compose -f compose.stage.yaml config --quiet
docker compose -f compose.stage.yaml pull
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$RACING_IMAGE")" == "$EXPECTED_SHA" ]]
docker compose -f compose.stage.yaml up -d --wait --wait-timeout 120 db
# Maintenance window: no old workers may write during the migration.
docker compose -f compose.stage.yaml stop web
# On failure leave the app stopped for controlled recovery. No destructive rollback.
docker compose -f compose.stage.yaml run --rm --no-deps web flask --app run db upgrade
docker compose -f compose.stage.yaml run --rm --no-deps web flask --app run db check
docker compose -f compose.stage.yaml up -d --no-build --wait --wait-timeout 120 web
python3 scripts/smoke.py "http://127.0.0.1:${WEB_PORT:-8080}"
