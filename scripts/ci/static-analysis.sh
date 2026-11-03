#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
exec "${STATIC_PYTHON:-$PWD/.static-tools/bin/python}" scripts/ci/static_analysis.py "${1:-all}"
