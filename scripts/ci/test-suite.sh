#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
if [[ -n "${TEAMCITY_VERSION:-}" ]]; then
  : "${BUILD_VCS_NUMBER:?TeamCity must provide the checkout revision}"
  actual=$(git rev-parse HEAD)
  [[ "$actual" == "$BUILD_VCS_NUMBER" ]] || { echo 'Checkout differs from TeamCity revision' >&2; exit 1; }
fi
"${PYTHON:-python3}" scripts/ci/run_tests.py "${1:?Usage: scripts/ci/test-suite.sh unit|integration}"
