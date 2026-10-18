#!/usr/bin/env bash
set -euo pipefail

if [[ "${BAREMETAL_HARNESS_REAL_MODEL:-}" != "1" ]]; then
  echo "set BAREMETAL_HARNESS_REAL_MODEL=1 to enable the opt-in real-model smoke" >&2
  exit 2
fi

missing=()
for name in OPENAI_BASE_URL OPENAI_API_KEY OPENAI_MODEL; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done
if (( ${#missing[@]} > 0 )); then
  printf 'missing required environment:' >&2
  printf ' %s' "${missing[@]}" >&2
  printf '\n' >&2
  exit 2
fi

uv run python scripts/real_model_smoke.py
