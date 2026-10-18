#!/usr/bin/env bash
set -euo pipefail

source_repo="${1:-.}"
source_repo="$(cd "$source_repo" && pwd -P)"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

git clone --no-local "$source_repo" "$workdir/baremetal-harness"
cd "$workdir/baremetal-harness"

branch="$(git -C "$source_repo" branch --show-current)"
if [[ -n "$branch" ]] && git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  git checkout --detach "origin/$branch"
fi

uv python install 3.12
uv sync --extra dev --python 3.12
uv run python --version
uv run bash scripts/smoke_offline.sh
