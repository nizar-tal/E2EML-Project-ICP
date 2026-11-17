#!/usr/bin/env bash
# Single entry point: regenerate report, or run SLA + T6 then report.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SERVICE="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_HOST="${RUNS_HOST:-$HOME/icp/runs}"
LAPTOP_RUNS="${LAPTOP_RUNS:-$ROOT/runs}"
SERVICE_RESULTS="$SERVICE/results"

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

# Prefer local work/runs, then VM host runs, then committed results/ in this folder.
RUNS="$LAPTOP_RUNS"
if [[ ! -f "$RUNS/t6/index.json" && -f "$RUNS_HOST/t6/index.json" ]]; then
  RUNS="$RUNS_HOST"
fi
if [[ ! -f "$RUNS/t6/index.json" && -f "$SERVICE_RESULTS/t6/index.json" ]]; then
  RUNS="$SERVICE_RESULTS"
fi
if [[ ! -f "$RUNS/t6/index.json" || ! -f "$RUNS/sla.json" ]]; then
  echo "missing t6/index.json or sla.json (tried $LAPTOP_RUNS, $RUNS_HOST, $SERVICE_RESULTS)" >&2
  exit 1
fi

OUT="${REPORT_OUT:-$RUNS/report}"
rm -rf "$OUT"
mkdir -p "$OUT"
python3 "$SERVICE/profile/report.py" --runs "$RUNS" --out "$OUT"
echo "report ready under $OUT (runs=$RUNS)"
ls -la "$OUT"
