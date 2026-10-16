#!/usr/bin/env bash
# TeamCity deploy runner. SSH identity comes from its dedicated SSH Agent feature.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/../.."
: "${EXPECTED_SHA:?Revision of the successful snapshot dependency}"
: "${UPSTREAM_BUILD_ID:?ID of that same successful dependency}"
: "${STAGE_KNOWN_HOSTS:?Private file containing independently verified STAGE host key}"
[[ -s "$STAGE_KNOWN_HOSTS" ]]
[[ "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ && "$UPSTREAM_BUILD_ID" =~ ^[0-9]{1,15}$ ]]
metadata=$(python3 - "$EXPECTED_SHA" "$UPSTREAM_BUILD_ID" <<'PY'
import hashlib, json, re, sys
with open('artifacts/published-image.json') as stream:
    data = json.load(stream)
assert data['sha'] == sys.argv[1] and data['build_id'] == sys.argv[2]
assert re.fullmatch(r'skre4karta/racing-club@sha256:[a-f0-9]{64}', data['image'])
with open('artifacts/stage-deploy.tar.gz', 'rb') as bundle:
    assert hashlib.file_digest(bundle, 'sha256').hexdigest() == data['bundle_sha256']
print(data['image'])
PY
)
ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$STAGE_KNOWN_HOSTS" -o ConnectTimeout=10)
# Fixed destination prevents runtime parameters from accidentally targeting PROD.
target=zelyonka@10.20.0.12
release="/home/zelyonka/racing-cd/releases/$EXPECTED_SHA-$UPSTREAM_BUILD_ID"
ssh "${ssh_opts[@]}" "$target" "umask 077; mkdir -p '$release'"
scp "${ssh_opts[@]}" artifacts/stage-deploy.tar.gz "$target:$release/stage-deploy.tar.gz"
ssh "${ssh_opts[@]}" "$target" bash -s -- "$release" "$EXPECTED_SHA" "$metadata" "$UPSTREAM_BUILD_ID" <<'REMOTE'
set -Eeuo pipefail
umask 077
release=$1
accepted_sha=$2
accepted_image=$3
accepted_build=$4
root=/home/zelyonka/racing-cd
mkdir -p "$root/state"
exec 8>"$root/state/pipeline.lock"
flock -n 8 || { echo 'Another STAGE pipeline is running' >&2; exit 1; }
cd "$release"
tar -xzf stage-deploy.tar.gz
# Trusted local deployment config, outside Git; shell syntax, owned by deploy user.
settings="$root/stage-deploy.env"
[[ -f "$settings" && ! -L "$settings" && "$(stat -c %a "$settings")" == 600 && -O "$settings" ]]
set -a
source "$settings"
set +a
# Accepted artifact values override any older values in local settings.
export EXPECTED_SHA="$accepted_sha" RACING_IMAGE="$accepted_image" BUILD_ID="$accepted_build"
export DEPLOY_ENV=STAGE COMPOSE_PROJECT_NAME=racing-club-beta1
export DEPLOY_STATE_DIR="$root/state" STAGE_ENV_FILE="$settings"
[[ "$STAGE_DATABASE_NAME" =~ ^racing_(club_beta1|stage_[a-z0-9_]+|demo_[a-z0-9_]+)$ ]]
attempt=$(mktemp -d "$root/state/pipeline.XXXXXXXX")
export BACKUP_PATH="$attempt/before.dump" REHEARSAL_RECEIPT="$attempt/receipt.json"
docker exec racing-club-stage-db-1 sh -c 'exec pg_dump -U "$POSTGRES_USER" -Fc "$1"' sh "$STAGE_DATABASE_NAME" > "$BACKUP_PATH"
bash scripts/ci/rehearse-stage.sh
bash scripts/ci/deploy-stage.sh
REMOTE
# Returning success requires every remote operation including health/smoke to pass.
