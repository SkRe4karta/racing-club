#!/usr/bin/env bash
# Linux x86_64; isolated dependencies, no system installation or sudo.
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
tools="${STATIC_TOOLS_DIR:-$PWD/.static-tools}"
[[ "$(uname -m)" == x86_64 ]] || { printf 'Expected Linux x86_64\n' >&2; exit 2; }
mkdir -p artifacts/static-analysis
rm -f artifacts/static-analysis/quality/report.json artifacts/static-analysis/security/report.json \
  artifacts/static-analysis/secrets/report.json artifacts/static-analysis/summary.html
python3 -m venv "$tools"
"$tools/bin/python" -m pip install --disable-pip-version-check -r scripts/ci/static-analysis-requirements.txt
archive=$(mktemp)
trap 'rm -f "$archive"' EXIT
curl --fail --silent --show-error --location \
  https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz \
  --output "$archive"
printf '%s  %s\n' a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$tools/bin" gitleaks
"$tools/bin/ruff" --version
"$tools/bin/bandit" --version
"$tools/bin/gitleaks" version
