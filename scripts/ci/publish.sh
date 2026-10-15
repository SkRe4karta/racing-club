#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
: "${TC_BRANCH:?TeamCity logical branch required}"
: "${DOCKERHUB_REPOSITORY:?Set namespace/racing-club}"
: "${DOCKERHUB_USER:?Protected TeamCity parameter}"
: "${DOCKERHUB_TOKEN:?Protected TeamCity password parameter}"
[[ "$TC_BRANCH" == dev ]] || { echo 'Only accepted dev builds can publish' >&2; exit 1; }
sha=$(git rev-parse HEAD)
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
docker image inspect --format '{{join .RepoDigests "\n"}}' "$tag" > artifacts/registry-digests.txt
