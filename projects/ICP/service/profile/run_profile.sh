#!/usr/bin/env bash
# Single entry point: regenerate report, or run SLA + T6 then report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SERVICE="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_HOST="${RUNS_HOST:-$HOME/icp/runs}"
LAPTOP_RUNS="${LAPTOP_RUNS:-$ROOT/runs}"

usage() {
  echo "usage: $0 [--report-only]"
  exit 1
}

REPORT_ONLY=0
if [[ "${1:-}" == "--report-only" ]]; then
  REPORT_ONLY=1
elif [[ -n "${1:-}" ]]; then
  usage
fi

if [[ "$REPORT_ONLY" -eq 0 ]]; then
  python3 "$SERVICE/profile/calibrate_sla.py"
  python3 "$SERVICE/profile/sweep_t6.py" --reduced
fi

RUNS="$LAPTOP_RUNS"
if [[ ! -f "$RUNS/t6/index.json" && -f "$RUNS_HOST/t6/index.json" ]]; then
  RUNS="$RUNS_HOST"
fi

rm -rf "$RUNS/report"
mkdir -p "$RUNS/report"
python3 "$SERVICE/profile/report.py" --runs "$RUNS" --out "$RUNS/report"
echo "report ready under $RUNS/report"
ls -la "$RUNS/report"
