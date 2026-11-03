#!/usr/bin/env bash
# Run on the authorized TEST Docker agent. No registry or remote server writes.
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
sha=$(git rev-parse HEAD)
: "${EXPECTED_SHA:?Set to TeamCity build.vcs.number}"
[[ "$sha" == "$EXPECTED_SHA" ]] || { echo 'Checkout differs from TeamCity revision' >&2; exit 1; }
version=2.0.0-beta.1
suffix="${sha:0:12}-$$"
network="racing-ci-$suffix"
postgres="racing-ci-pg-$suffix"
web="racing-ci-web-$suffix"
checks="racing-checks:$suffix"
image="racing-verified:$version-${sha:0:12}"
mkdir -p artifacts
# An unsuccessful run must not leave an older success receipt for publication.
rm -f artifacts/verified-image.txt artifacts/published-image.json artifacts/registry-digests.txt artifacts/stage-deploy.tar.gz
test_containers=()
cleanup() {
  docker rm -f "$web" "$postgres" "${test_containers[@]}" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
# No production env files or credentials are mounted into test containers.
git diff --exit-code
git diff --cached --exit-code
git diff --check
docker build --target checks -t "$checks" .
mkdir -p artifacts/tests
rm -f artifacts/tests/unit.xml artifacts/tests/integration.xml artifacts/tests/ci-integration.xml artifacts/tests/postgres.xml
run_test_suite() {
  local suite="$1" test_network="$2" container="racing-tests-$suffix-$1" result=0
  test_containers+=("$container")
  docker create --name "$container" --network "$test_network" \
    -e LAB7_GIT_SHA="$sha" -e LAB7_REPORT_DIR=/tmp/racing-test-reports \
    -e RACING_TEST_POSTGRES_URL="${3:-}" \
    "$checks" python scripts/ci/run_tests.py "$suite" >/dev/null
  docker start -a "$container" || result=$?
  docker cp "$container:/tmp/racing-test-reports/$suite.xml" "artifacts/tests/$suite.xml" || result=1
  docker rm "$container" >/dev/null
  if [[ -s "artifacts/tests/$suite.xml" ]]; then
    printf "##teamcity[importData type='junit' path='artifacts/tests/%s.xml']\n" "$suite"
  fi
  return "$result"
}
run_test_suite unit none
run_test_suite ci-integration none
run_test_suite lab8-sqlite none
# Disposable container writable layer; no named volumes are created by this job.
docker network create --internal "$network" >/dev/null
docker run -d --name "$postgres" --network "$network" --tmpfs /var/lib/postgresql \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18-alpine >/dev/null
ready=false
for attempt in {1..60}; do
  if docker exec "$postgres" pg_isready -U postgres >/dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
"$ready" || { echo 'PostgreSQL did not become ready' >&2; exit 1; }
run_test_suite postgres "$network" "postgresql+psycopg://postgres@$postgres/postgres"
run_test_suite lab8-postgres "$network" "postgresql+psycopg://postgres@$postgres/postgres"
mkdir -p artifacts/schema
docker exec "$postgres" createdb -U postgres racing_lab8_schema
baseline=$(docker run --rm --network none "$checks" python -c 'from alembic.config import Config; from alembic.script import ScriptDirectory; c=Config(); c.set_main_option("script_location","migrations"); s=ScriptDirectory.from_config(c); print(s.get_revision(s.get_current_head()).down_revision)')
[[ "$baseline" =~ ^[a-zA-Z0-9_]+$ ]]
docker run --rm --network "$network" -e SECRET_KEY="isolated-schema-export-only" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_lab8_schema" \
  "$checks" flask --app run db upgrade "$baseline"
docker run --rm --network "$network" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_lab8_schema" \
  "$checks" python scripts/ci/schema_snapshot.py --expected-db racing_lab8_schema > artifacts/schema/baseline.json
docker run --rm --network "$network" -e SECRET_KEY="isolated-schema-export-only" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_lab8_schema" \
  "$checks" flask --app run db upgrade
bash scripts/ci/export-schema.sh "$postgres" racing_lab8_schema artifacts/schema
docker run --rm --network "$network" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_lab8_schema" \
  "$checks" python scripts/ci/schema_snapshot.py --expected-db racing_lab8_schema > artifacts/schema/structure.json

docker build --target runtime --build-arg VCS_REF="$sha" -t "$image" .
docker exec "$postgres" createdb -U postgres racing_ci_smoke
# Only ephemeral CI session key, no production credentials.
ci_secret=$(docker run --rm --network none "$checks" python -c 'import secrets; print(secrets.token_hex(32))')
docker run --rm --network "$network" -e SECRET_KEY="$ci_secret" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_ci_smoke" \
  "$image" flask --app run db upgrade
docker run -d --name "$web" --network "$network" -e SECRET_KEY="$ci_secret" \
  -e DATABASE_URL="postgresql+psycopg://postgres@$postgres/racing_ci_smoke" "$image" >/dev/null
ready=false
for attempt in {1..40}; do
  if docker exec "$web" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)" >/dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
"$ready" || { echo 'Application did not become healthy' >&2; exit 1; }
docker run --rm --network "$network" "$checks" python scripts/smoke.py "http://$web:8080"
printf 'VERSION=%s\nSHA=%s\nIMAGE=%s\nIMAGE_ID=%s\n' "$version" "$sha" "$image" \
  "$(docker image inspect --format '{{.Id}}' "$image")" > artifacts/verified-image.txt
# Publish only from the dev build immediately after this successful step.
