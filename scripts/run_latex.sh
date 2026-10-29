#!/usr/bin/env bash
# Run the bundled example with an authenticated coding CLI and measured stage timeout.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$#" -lt 2 ]; then
  echo "usage: bash run_latex.sh codex|claude <timeout-seconds> [extra pipeline arguments]" >&2
  exit 64
fi
BACKEND="$1"
STAGE_TIMEOUT="$2"
shift 2
exec "${PYTHON:-python3}" "$ROOT/codes/pipeline.py" --backend "$BACKEND" --timeout "$STAGE_TIMEOUT" --paper_name Transformer --paper_format LaTeX --input "$ROOT/examples/Transformer_cleaned.tex" --output_dir "$ROOT/outputs/Transformer" --output_repo_dir "$ROOT/outputs/Transformer_repo" "$@"
