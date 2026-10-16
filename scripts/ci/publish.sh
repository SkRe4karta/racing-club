#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
: "${TC_BRANCH:?TeamCity logical branch required}"
: "${DOCKERHUB_REPOSITORY:?Set namespace/racing-club}"
: "${DOCKERHUB_USER:?Protected TeamCity parameter}"
: "${DOCKERHUB_TOKEN:?Protected TeamCity password parameter}"
: "${EXPECTED_SHA:?Set to TeamCity build.vcs.number}"
: "${BUILD_ID:?Set to TeamCity build.id}"
[[ "$TC_BRANCH" == dev ]] || { echo 'Only accepted dev builds can publish' >&2; exit 1; }
sha=$(git rev-parse HEAD)
[[ "$sha" == "$EXPECTED_SHA" && "$BUILD_ID" =~ ^[0-9]+$ ]]
[[ "$DOCKERHUB_REPOSITORY" == skre4karta/racing-club ]]
rm -f artifacts/published-image.json artifacts/registry-digests.txt artifacts/stage-deploy.tar.gz
image="racing-verified:2.0.0-beta.1-${sha:0:12}"
test -s artifacts/verified-image.txt
# Exact local image ID must match the successful verification output.
actual=$(docker image inspect --format '{{.Id}}' "$image")
rg_fixed="IMAGE_ID=$actual"
grep -Fxq "$rg_fixed" artifacts/verified-image.txt
grep -Fxq "SHA=$sha" artifacts/verified-image.txt
[[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" == "$sha" ]]
registry_config=$(mktemp -d)
trap 'rm -rf "$registry_config"' EXIT
export DOCKER_CONFIG="$registry_config"
printf '%s' "$DOCKERHUB_TOKEN" | docker login --username "$DOCKERHUB_USER" --password-stdin >/dev/null
tag="$DOCKERHUB_REPOSITORY:2.0.0-beta.1-${sha:0:12}"
docker tag "$image" "$tag"
docker push "$tag"
# Select this repository's digest, never a different tag attached to the local image.
digest=$(docker image inspect --format '{{join .RepoDigests "\n"}}' "$tag" | grep -E "^${DOCKERHUB_REPOSITORY}@sha256:[a-f0-9]{64}$")
[[ "$digest" =~ ^skre4karta/racing-club@sha256:[a-f0-9]{64}$ ]]
docker pull "$digest"
[[ "$(docker image inspect --format '{{.Id}}' "$digest")" == "$actual" ]]
printf '%s\n' "$digest" > artifacts/registry-digests.txt
tar -czf artifacts/stage-deploy.tar.gz compose.stage.yaml scripts/ci/deploy-stage.sh scripts/ci/rehearse-stage.sh scripts/ci/schema-state.py scripts/smoke.py
bundle_sha=$(sha256sum artifacts/stage-deploy.tar.gz | cut -d ' ' -f 1)
python3 - "$sha" "$tag" "$digest" "$BUILD_ID" "$bundle_sha" <<'PY'
import json, pathlib, sys
sha, tag, image, build_id, bundle_sha = sys.argv[1:]
pathlib.Path('artifacts/published-image.json').write_text(json.dumps(dict(
    version='2.0.0-beta.1', sha=sha, tag=tag, image=image,
    build_id=build_id, bundle_sha256=bundle_sha), indent=2) + '\n')
PY
