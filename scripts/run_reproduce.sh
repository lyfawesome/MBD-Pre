#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"
DOWNLOAD_WORKERS="${MBD_DOWNLOAD_WORKERS:-16}"
INSPECTION_WORKERS="${MBD_INSPECTION_WORKERS:-2}"
PRECISION_WORKERS="${MBD_PRECISION_WORKERS:-8}"
MODE="${1:-full}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 2
fi
if ! command -v DRAWEXE >/dev/null 2>&1; then
  echo "DRAWEXE is not on PATH. Create and activate the environment.yml environment first." >&2
  exit 2
fi

case "$MODE" in
  test)
    "$PYTHON_BIN" -m unittest -v
    ;;
  sample)
    "$PYTHON_BIN" step_geometry_encoder.py data/input/motor.STEP \
      --output runs/reproduction/motor --precision-mode boolean
    ;;
  full)
    "$PYTHON_BIN" -m unittest -v
    "$PYTHON_BIN" scripts/acquire_assembly_data.py \
      --workers "$DOWNLOAD_WORKERS" --retries 5
    "$PYTHON_BIN" scripts/inspect_step_assemblies.py \
      --workers "$INSPECTION_WORKERS" --minimum-solids 10
    "$PYTHON_BIN" scripts/run_assembly_corpus.py \
      --precision-mode boolean --precision-workers "$PRECISION_WORKERS" --skip-step-export
    "$PYTHON_BIN" scripts/evaluate_stability.py --order-trials 10
    "$PYTHON_BIN" scripts/evaluate_rigid_invariance.py
    "$PYTHON_BIN" scripts/build_human_review.py
    "$PYTHON_BIN" scripts/build_research_audit.py
    "$PYTHON_BIN" scripts/summarize_corpus.py
    ;;
  *)
    echo "Usage: scripts/run_reproduce.sh [test|sample|full]" >&2
    exit 2
    ;;
esac
