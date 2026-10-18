#!/usr/bin/env bash
set -euo pipefail

report_dir="$(mktemp -d)"
trap 'rm -rf "$report_dir"' EXIT

uv run pytest -q
uv run python -m baremetal_harness.evals.cli run tests/fixtures/evals/core.json \
  --output "$report_dir"
uv run python examples/full_agent_flow.py --fake
uv run python scripts/scan_repository.py
